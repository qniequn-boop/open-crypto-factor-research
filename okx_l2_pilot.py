"""Bounded OKX historical L2 feasibility and executable-cost pilot.

The raw order-book archive is newline-delimited JSON containing one snapshot
and incremental updates. Derivative sizes are contracts, so quote depth uses
the contemporaneous instrument contract value. This module reconstructs the
book as a stream; it does not load an uncompressed day into memory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import tarfile
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import requests

import config
import data as data_module


DOWNLOAD_LINK_ENDPOINT = (
    f"{config.OKX_BASE_URL}/priapi/v5/broker/public/trade-data/download-link"
)
ALLOWED_DOWNLOAD_PREFIX = "https://static.okx.com/"
L2_400_MODULE = "4"
TRADE_HISTORY_MODULE = "1"
DEFAULT_PILOT_DATE = date(2026, 7, 10)
DEFAULT_INSTRUMENTS = (
    "XRP-USDT-SWAP",
    "LDO-USDT-SWAP",
    "TRX-USDT-SWAP",
)
DEFAULT_NOTIONALS = (100.0, 1_000.0, 10_000.0)
DEFAULT_DEPTH_BPS = (5.0, 10.0, 25.0, 50.0)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _day_bounds(day: date) -> tuple[int, int]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    start_ms = int(start.timestamp() * 1000)
    return start_ms, start_ms + 86_400_000


def _family(inst_id: str) -> str:
    if not inst_id.endswith("-SWAP"):
        raise ValueError(f"l2_pilot_requires_swap:{inst_id}")
    return inst_id[:-5]


def request_download_links(
    inst_ids: Iterable[str],
    *,
    module: str,
    begin_ms: int,
    end_ms_exclusive: int,
    session: Any = None,
) -> list[dict[str, Any]]:
    """Request public OKX archive metadata without downloading the files."""

    client = session or requests
    payload = {
        "module": str(module),
        "instType": "SWAP",
        "instQueryParam": {
            "instFamilyList": [_family(inst_id) for inst_id in inst_ids],
        },
        "dateQuery": {
            "dateAggrType": "daily",
            "begin": str(int(begin_ms)),
            "end": str(int(end_ms_exclusive) - 1),
        },
    }
    headers = {
        "user-agent": "Mozilla/5.0",
        "referer": f"{config.OKX_BASE_URL}/historical-data",
        "content-type": "application/json",
    }
    response = None
    for attempt in range(5):
        response = client.post(
            DOWNLOAD_LINK_ENDPOINT,
            json=payload,
            headers=headers,
            timeout=60,
        )
        status = int(getattr(response, "status_code", 200))
        if status not in (429, 500, 502, 503, 504):
            break
        retry_after = float(getattr(response, "headers", {}).get("Retry-After", 0) or 0)
        time.sleep(max(retry_after, min(2 ** attempt, 16)))
    if response is None:
        raise IOError("OKX historical-data link request produced no response")
    response.raise_for_status()
    body = response.json()
    if body.get("code") != "0":
        raise IOError(f"OKX historical-data link error: {body.get('msg')}")

    rows: list[dict[str, Any]] = []
    for detail in (body.get("data") or {}).get("details") or []:
        inst_family = str(detail.get("instFamily") or "")
        for item in detail.get("groupDetails") or []:
            url = str(item.get("url") or "")
            filename = str(item.get("filename") or "")
            if not url.startswith(ALLOWED_DOWNLOAD_PREFIX):
                raise ValueError(f"untrusted_okx_archive_url:{url}")
            if not filename or Path(filename).name != filename:
                raise ValueError(f"unsafe_okx_archive_filename:{filename}")
            rows.append(
                {
                    "module": str(module),
                    "inst_family": inst_family,
                    "inst_id": f"{inst_family}-SWAP",
                    "date_ts": int(item["dateTs"]),
                    "filename": filename,
                    "size_mb": float(item.get("sizeMB") or 0.0),
                    "url": url,
                }
            )
    return rows


def discover_pilot_archives(
    inst_ids: Iterable[str],
    pilot_date: date,
    *,
    session: Any = None,
) -> dict[str, list[dict[str, Any]]]:
    inst_ids = tuple(inst_ids)
    start_ms, end_ms = _day_bounds(pilot_date)
    l2 = request_download_links(
        inst_ids,
        module=L2_400_MODULE,
        begin_ms=start_ms,
        end_ms_exclusive=end_ms,
        session=session,
    )
    time.sleep(1.0)

    # OKX trade-history daily files use a 16:00 UTC boundary. Request the
    # preceding and target website dates, then filter rows by actual trade ts.
    trade_start_ms, _ = _day_bounds(pilot_date - timedelta(days=1))
    trades = request_download_links(
        inst_ids,
        module=TRADE_HISTORY_MODULE,
        begin_ms=trade_start_ms,
        end_ms_exclusive=end_ms,
        session=session,
    )
    requested = set(inst_ids)
    l2_ids = {row["inst_id"] for row in l2}
    if l2_ids != requested:
        raise ValueError(
            f"l2_archive_coverage_mismatch:missing={sorted(requested - l2_ids)}:"
            f"unexpected={sorted(l2_ids - requested)}"
        )
    if not requested.issubset({row["inst_id"] for row in trades}):
        raise ValueError("trade_archive_coverage_incomplete")
    return {"l2": l2, "trades": trades}


def _download_file(url: str, destination: Path, *, session: Any = None) -> dict[str, Any]:
    if not url.startswith(ALLOWED_DOWNLOAD_PREFIX):
        raise ValueError(f"untrusted_okx_archive_url:{url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return {
            "path": str(destination),
            "bytes": int(destination.stat().st_size),
            "sha256": _sha256(destination),
            "downloaded": False,
        }

    client = session or requests
    part = destination.with_suffix(destination.suffix + ".part")
    response = client.get(url, stream=True, timeout=(30, 300))
    response.raise_for_status()
    try:
        with part.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        if part.stat().st_size <= 0:
            raise IOError(f"empty_okx_archive:{destination.name}")
        part.replace(destination)
    finally:
        if part.exists():
            part.unlink()
    return {
        "path": str(destination),
        "bytes": int(destination.stat().st_size),
        "sha256": _sha256(destination),
        "downloaded": True,
    }


def download_archives(
    discovered: dict[str, list[dict[str, Any]]],
    cache_dir: Path,
    *,
    session: Any = None,
) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {"l2": [], "trades": []}
    for archive_type in ("l2", "trades"):
        for row in discovered[archive_type]:
            provenance = _download_file(
                row["url"],
                cache_dir / row["filename"],
                session=session,
            )
            output[archive_type].append({**row, **provenance})
            time.sleep(0.1)
    return output


def fetch_instrument_specs(inst_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    requested = set(inst_ids)
    rows = data_module.fetch_okx_instruments("SWAP")
    specs: dict[str, dict[str, Any]] = {}
    for row in rows:
        inst_id = str(row.get("instId") or "")
        if inst_id not in requested:
            continue
        if row.get("ctType") != "linear" or row.get("ctValCcy") != inst_id.split("-")[0]:
            raise ValueError(f"unsupported_contract_conversion:{inst_id}")
        specs[inst_id] = {
            "inst_id": inst_id,
            "contract_value_base": float(row["ctVal"]),
            "contract_value_ccy": str(row["ctValCcy"]),
            "contract_type": str(row["ctType"]),
            "lot_size_contracts": float(row["lotSz"]),
            "minimum_size_contracts": float(row["minSz"]),
            "tick_size": float(row["tickSz"]),
            "state": str(row["state"]),
        }
    if set(specs) != requested:
        raise ValueError(f"instrument_specs_missing:{sorted(requested - set(specs))}")
    return specs


def apply_levels(book: dict[float, float], updates: Iterable[Iterable[Any]]) -> None:
    for level in updates:
        price = float(level[0])
        size = float(level[1])
        if size <= 0:
            book.pop(price, None)
        else:
            book[price] = size


def _ordered_levels(book: dict[float, float], *, reverse: bool) -> list[tuple[float, float]]:
    return sorted(book.items(), key=lambda item: item[0], reverse=reverse)


def _sweep(
    levels: list[tuple[float, float]],
    *,
    target_notional: float,
    contract_value_base: float,
    mid: float,
    side: str,
) -> dict[str, Any]:
    remaining = float(target_notional)
    quote_spent = 0.0
    base_filled = 0.0
    levels_used = 0
    for price, contracts in levels:
        base_available = contracts * float(contract_value_base)
        quote_available = base_available * price
        quote_take = min(remaining, quote_available)
        base_take = quote_take / price
        quote_spent += quote_take
        base_filled += base_take
        remaining -= quote_take
        levels_used += 1
        if remaining <= max(1e-9, target_notional * 1e-12):
            break
    fill_fraction = 1.0 - max(remaining, 0.0) / float(target_notional)
    if fill_fraction < 1.0 - 1e-9 or base_filled <= 0:
        return {
            "fillable": False,
            "fill_fraction": float(fill_fraction),
            "impact_bps": None,
            "vwap": None,
            "levels_used": levels_used,
        }
    vwap = quote_spent / base_filled
    impact = (
        (vwap - mid) / mid * 10_000.0
        if side == "buy"
        else (mid - vwap) / mid * 10_000.0
    )
    return {
        "fillable": True,
        "fill_fraction": 1.0,
        "impact_bps": float(impact),
        "vwap": float(vwap),
        "levels_used": levels_used,
    }


def book_metrics(
    bids: dict[float, float],
    asks: dict[float, float],
    spec: dict[str, Any],
    *,
    depth_bps: Iterable[float] = DEFAULT_DEPTH_BPS,
    notionals: Iterable[float] = DEFAULT_NOTIONALS,
) -> dict[str, Any] | None:
    if not bids or not asks:
        return None
    bid_levels = _ordered_levels(bids, reverse=True)
    ask_levels = _ordered_levels(asks, reverse=False)
    best_bid = bid_levels[0][0]
    best_ask = ask_levels[0][0]
    if best_bid <= 0 or best_ask <= best_bid:
        return None
    mid = (best_bid + best_ask) / 2.0
    contract_value = float(spec["contract_value_base"])
    depth: dict[str, Any] = {}
    for band in depth_bps:
        bid_floor = mid * (1.0 - float(band) / 10_000.0)
        ask_ceiling = mid * (1.0 + float(band) / 10_000.0)
        bid_notional = sum(
            price * contracts * contract_value
            for price, contracts in bid_levels
            if price >= bid_floor
        )
        ask_notional = sum(
            price * contracts * contract_value
            for price, contracts in ask_levels
            if price <= ask_ceiling
        )
        depth[str(int(band) if float(band).is_integer() else band)] = {
            "bid_usdt": float(bid_notional),
            "ask_usdt": float(ask_notional),
        }
    impact: dict[str, Any] = {}
    for target in notionals:
        key = str(int(target) if float(target).is_integer() else target)
        impact[key] = {
            "buy": _sweep(
                ask_levels,
                target_notional=float(target),
                contract_value_base=contract_value,
                mid=mid,
                side="buy",
            ),
            "sell": _sweep(
                bid_levels,
                target_notional=float(target),
                contract_value_base=contract_value,
                mid=mid,
                side="sell",
            ),
        }
    bid_10 = depth.get("10", {}).get("bid_usdt", 0.0)
    ask_10 = depth.get("10", {}).get("ask_usdt", 0.0)
    total_10 = bid_10 + ask_10
    return {
        "best_bid": float(best_bid),
        "best_ask": float(best_ask),
        "mid": float(mid),
        "quoted_spread_bps": float((best_ask - best_bid) / mid * 10_000.0),
        "depth_usdt": depth,
        "imbalance_10bps": float((bid_10 - ask_10) / total_10) if total_10 > 0 else None,
        "impact": impact,
    }


def _summary(values: Iterable[float]) -> dict[str, Any]:
    clean = np.asarray([float(value) for value in values if math.isfinite(float(value))])
    if not len(clean):
        return {"count": 0}
    return {
        "count": int(len(clean)),
        "mean": float(clean.mean()),
        "p05": float(np.quantile(clean, 0.05)),
        "p25": float(np.quantile(clean, 0.25)),
        "median": float(np.quantile(clean, 0.50)),
        "p75": float(np.quantile(clean, 0.75)),
        "p95": float(np.quantile(clean, 0.95)),
        "minimum": float(clean.min()),
        "maximum": float(clean.max()),
    }


def load_trades(
    archive_paths: Iterable[Path],
    *,
    inst_id: str,
    start_ms: int,
    end_ms_exclusive: int,
) -> list[dict[str, Any]]:
    by_key: dict[tuple[int, str], dict[str, Any]] = {}
    for path in archive_paths:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.endswith(".csv"):
                    continue
                with archive.open(name) as raw:
                    reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))
                    for row in reader:
                        if row.get("instrument_name") != inst_id:
                            continue
                        timestamp = int(row["created_time"])
                        if not start_ms <= timestamp < end_ms_exclusive:
                            continue
                        trade = {
                            "timestamp_ms": timestamp,
                            "trade_id": str(row["trade_id"]),
                            "side": str(row["side"]).lower(),
                            "price": float(row["price"]),
                            "size_contracts": float(row["size"]),
                        }
                        by_key[(timestamp, trade["trade_id"])] = trade
    return sorted(by_key.values(), key=lambda row: (row["timestamp_ms"], row["trade_id"]))


def _iter_l2_messages(path: Path) -> Iterable[dict[str, Any]]:
    # Stream mode avoids decompressing a large tarball once for getmembers()
    # and a second time for the actual member contents.
    with tarfile.open(path, mode="r|gz") as archive:
        file_members = 0
        member_names = []
        for member in archive:
            if not member.isfile():
                continue
            file_members += 1
            member_names.append(member.name)
            if file_members > 1 or not member.name.endswith(".data"):
                raise ValueError(f"unexpected_l2_archive_members:{member_names}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError("l2_archive_member_unreadable")
            with extracted:
                for line_number, raw_line in enumerate(extracted, start=1):
                    if not raw_line.strip():
                        continue
                    try:
                        yield json.loads(raw_line)
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ValueError(f"invalid_l2_json_line:{line_number}") from exc
        if file_members != 1:
            raise ValueError(f"unexpected_l2_archive_members:{member_names}")


def analyze_l2_archive(
    l2_path: Path,
    *,
    spec: dict[str, Any],
    trades: list[dict[str, Any]],
    start_ms: int,
    end_ms_exclusive: int,
    sample_interval_ms: int = 10_000,
    depth_bps: Iterable[float] = DEFAULT_DEPTH_BPS,
    notionals: Iterable[float] = DEFAULT_NOTIONALS,
) -> dict[str, Any]:
    bids: dict[float, float] = {}
    asks: dict[float, float] = {}
    spread_values: list[float] = []
    imbalance_values: list[float] = []
    stale_values: list[float] = []
    depth_values = {
        str(int(band) if float(band).is_integer() else band): {"bid": [], "ask": []}
        for band in depth_bps
    }
    impact_values = {
        str(int(target) if float(target).is_integer() else target): {
            "buy": [],
            "sell": [],
            "buy_attempts": 0,
            "sell_attempts": 0,
        }
        for target in notionals
    }
    effective_spreads: list[float] = []
    effective_weights: list[float] = []
    trade_quote_age_ms: list[float] = []
    matched_trade_notional = 0.0
    total_trade_notional = sum(
        row["price"] * row["size_contracts"] * float(spec["contract_value_base"])
        for row in trades
    )

    message_count = 0
    snapshots = 0
    updates = 0
    monotonic_violations = 0
    first_event_ms: int | None = None
    last_event_ms: int | None = None
    maximum_event_gap_ms = 0
    last_book_event_ms: int | None = None
    next_sample_ms = int(start_ms)
    valid_samples = 0
    invalid_samples = 0
    trade_index = 0

    def current_mid() -> float | None:
        if not bids or not asks:
            return None
        best_bid = max(bids)
        best_ask = min(asks)
        if best_ask <= best_bid:
            return None
        return (best_bid + best_ask) / 2.0

    def match_trades(through_ms: int) -> None:
        nonlocal trade_index, matched_trade_notional
        while trade_index < len(trades) and trades[trade_index]["timestamp_ms"] <= through_ms:
            trade = trades[trade_index]
            trade_index += 1
            mid = current_mid()
            if mid is None or last_book_event_ms is None:
                continue
            direction = 1.0 if trade["side"] == "buy" else -1.0
            effective = 2.0 * direction * (trade["price"] - mid) / mid * 10_000.0
            quote_notional = (
                trade["price"]
                * trade["size_contracts"]
                * float(spec["contract_value_base"])
            )
            effective_spreads.append(float(effective))
            effective_weights.append(float(quote_notional))
            trade_quote_age_ms.append(float(trade["timestamp_ms"] - last_book_event_ms))
            matched_trade_notional += quote_notional

    def emit_sample(sample_ms: int) -> None:
        nonlocal valid_samples, invalid_samples
        metrics = book_metrics(
            bids,
            asks,
            spec,
            depth_bps=depth_bps,
            notionals=notionals,
        )
        if metrics is None:
            invalid_samples += 1
            return
        valid_samples += 1
        spread_values.append(metrics["quoted_spread_bps"])
        if metrics["imbalance_10bps"] is not None:
            imbalance_values.append(metrics["imbalance_10bps"])
        if last_book_event_ms is not None:
            stale_values.append(max(0.0, float(sample_ms - last_book_event_ms)))
        for band, values in metrics["depth_usdt"].items():
            depth_values[band]["bid"].append(values["bid_usdt"])
            depth_values[band]["ask"].append(values["ask_usdt"])
        for target, sides in metrics["impact"].items():
            for side in ("buy", "sell"):
                impact_values[target][f"{side}_attempts"] += 1
                if sides[side]["fillable"]:
                    impact_values[target][side].append(sides[side]["impact_bps"])

    for message in _iter_l2_messages(l2_path):
        if message.get("instId") != spec["inst_id"]:
            raise ValueError(f"l2_instrument_mismatch:{message.get('instId')}")
        timestamp = int(message["ts"])
        if timestamp < start_ms:
            continue
        if timestamp >= end_ms_exclusive:
            break
        message_count += 1
        if first_event_ms is None:
            first_event_ms = timestamp
        if last_event_ms is not None:
            if timestamp < last_event_ms:
                monotonic_violations += 1
            maximum_event_gap_ms = max(maximum_event_gap_ms, timestamp - last_event_ms)

        action = message.get("action")
        initial_snapshot = action == "snapshot" and snapshots == 0
        match_trades(timestamp)
        if not initial_snapshot:
            while next_sample_ms < timestamp and next_sample_ms < end_ms_exclusive:
                emit_sample(next_sample_ms)
                next_sample_ms += int(sample_interval_ms)

        if action == "snapshot":
            bids.clear()
            asks.clear()
            snapshots += 1
        elif action == "update":
            updates += 1
        else:
            raise ValueError(f"unknown_l2_action:{action}")
        apply_levels(bids, message.get("bids") or [])
        apply_levels(asks, message.get("asks") or [])
        last_event_ms = timestamp
        last_book_event_ms = timestamp

        while next_sample_ms <= timestamp and next_sample_ms < end_ms_exclusive:
            emit_sample(next_sample_ms)
            next_sample_ms += int(sample_interval_ms)

    while next_sample_ms < end_ms_exclusive:
        emit_sample(next_sample_ms)
        next_sample_ms += int(sample_interval_ms)
    match_trades(end_ms_exclusive - 1)

    expected_samples = int(math.ceil((end_ms_exclusive - start_ms) / sample_interval_ms))
    effective_weighted = (
        float(np.average(effective_spreads, weights=effective_weights))
        if effective_spreads and sum(effective_weights) > 0
        else None
    )
    negative_effective_fraction = (
        float(np.mean(np.asarray(effective_spreads) < 0)) if effective_spreads else None
    )
    minimum_order_notional = None
    if spread_values and bids and asks:
        mid = current_mid()
        if mid is not None:
            minimum_order_notional = (
                mid
                * float(spec["contract_value_base"])
                * float(spec["minimum_size_contracts"])
            )

    return {
        "inst_id": spec["inst_id"],
        "source_file": str(l2_path),
        "source_sha256": _sha256(l2_path),
        "start_utc": datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
        "end_utc_exclusive": datetime.fromtimestamp(
            end_ms_exclusive / 1000, tz=timezone.utc
        ).isoformat(),
        "instrument_spec": spec,
        "minimum_order_notional_usdt_at_last_mid": minimum_order_notional,
        "book_integrity": {
            "message_count": message_count,
            "snapshot_count": snapshots,
            "update_count": updates,
            "first_event_ms": first_event_ms,
            "last_event_ms": last_event_ms,
            "monotonic_timestamp_violations": monotonic_violations,
            "maximum_event_gap_ms": maximum_event_gap_ms,
            "final_bid_levels": len(bids),
            "final_ask_levels": len(asks),
        },
        "sampling": {
            "interval_ms": int(sample_interval_ms),
            "expected_samples": expected_samples,
            "valid_samples": valid_samples,
            "invalid_samples": invalid_samples,
            "coverage_fraction": valid_samples / expected_samples if expected_samples else 0.0,
            "quote_staleness_ms": _summary(stale_values),
            "stale_over_one_second_fraction": float(
                np.mean(np.asarray(stale_values) > 1_000.0)
            )
            if stale_values
            else None,
        },
        "quoted_spread_bps": _summary(spread_values),
        "imbalance_10bps": _summary(imbalance_values),
        "depth_usdt": {
            band: {"bid": _summary(values["bid"]), "ask": _summary(values["ask"])}
            for band, values in depth_values.items()
        },
        "market_order_impact_bps": {
            target: {
                "buy": {
                    **_summary(values["buy"]),
                    "fraction_above_current_fixed_slippage": float(
                        np.mean(np.asarray(values["buy"]) > float(config.SLIPPAGE_BPS))
                    )
                    if values["buy"]
                    else None,
                },
                "sell": {
                    **_summary(values["sell"]),
                    "fraction_above_current_fixed_slippage": float(
                        np.mean(np.asarray(values["sell"]) > float(config.SLIPPAGE_BPS))
                    )
                    if values["sell"]
                    else None,
                },
                "buy_fill_fraction": len(values["buy"]) / values["buy_attempts"]
                if values["buy_attempts"]
                else 0.0,
                "sell_fill_fraction": len(values["sell"]) / values["sell_attempts"]
                if values["sell_attempts"]
                else 0.0,
            }
            for target, values in impact_values.items()
        },
        "effective_spread_bps": {
            **_summary(effective_spreads),
            "quote_notional_weighted_mean": effective_weighted,
            "quote_notional_weighted_one_way_slippage_bps": effective_weighted / 2.0
            if effective_weighted is not None
            else None,
            "negative_fraction": negative_effective_fraction,
            "matched_trade_count": len(effective_spreads),
            "total_trade_count": len(trades),
            "matched_trade_fraction": len(effective_spreads) / len(trades) if trades else 0.0,
            "matched_trade_notional_usdt": float(matched_trade_notional),
            "total_trade_notional_usdt": float(total_trade_notional),
            "matched_trade_notional_fraction": matched_trade_notional / total_trade_notional
            if total_trade_notional > 0
            else 0.0,
            "quote_age_ms": _summary(trade_quote_age_ms),
            "method": "two_times_signed_trade_price_minus_preceding_mid; trade side is OKX aggressor side",
        },
    }


def run_pilot(
    *,
    pilot_date: date,
    inst_ids: Iterable[str],
    cache_dir: Path,
    sample_interval_ms: int = 10_000,
) -> dict[str, Any]:
    inst_ids = tuple(inst_ids)
    start_ms, end_ms = _day_bounds(pilot_date)
    discovered = discover_pilot_archives(inst_ids, pilot_date)
    downloaded = download_archives(discovered, cache_dir)
    specs = fetch_instrument_specs(inst_ids)

    assets: dict[str, Any] = {}
    for inst_id in inst_ids:
        l2_rows = [row for row in downloaded["l2"] if row["inst_id"] == inst_id]
        if len(l2_rows) != 1:
            raise ValueError(f"expected_one_l2_archive:{inst_id}:{len(l2_rows)}")
        trade_rows = [row for row in downloaded["trades"] if row["inst_id"] == inst_id]
        trades = load_trades(
            [Path(row["path"]) for row in trade_rows],
            inst_id=inst_id,
            start_ms=start_ms,
            end_ms_exclusive=end_ms,
        )
        assets[inst_id] = analyze_l2_archive(
            Path(l2_rows[0]["path"]),
            spec=specs[inst_id],
            trades=trades,
            start_ms=start_ms,
            end_ms_exclusive=end_ms,
            sample_interval_ms=sample_interval_ms,
        )

    feasible = all(
        row["book_integrity"]["snapshot_count"] >= 1
        and row["book_integrity"]["monotonic_timestamp_violations"] == 0
        and row["sampling"]["coverage_fraction"] >= 0.99
        and row["effective_spread_bps"]["matched_trade_fraction"] >= 0.99
        for row in assets.values()
    )
    return {
        "created_at_utc": _stamp(),
        "schema_version": 1,
        "audit_type": "okx_historical_l2_feasibility_pilot",
        "claim_ceiling": "one_day_three_asset_data_and_execution_cost_feasibility_only",
        "factor_generated": False,
        "parameter_search_performed": False,
        "promotion_state_changed": False,
        "pilot_date": pilot_date.isoformat(),
        "instruments": list(inst_ids),
        "sample_interval_ms": int(sample_interval_ms),
        "notionals_usdt": list(DEFAULT_NOTIONALS),
        "depth_bands_bps": list(DEFAULT_DEPTH_BPS),
        "current_backtest_cost_model": {
            "fee_bps_one_way": float(config.COST_BPS),
            "fixed_slippage_bps_one_way": float(config.SLIPPAGE_BPS),
            "all_in_bps_one_way": float(config.COST_BPS + config.SLIPPAGE_BPS),
            "comparison_rule": "visible_book_all_in_cost_equals_fee_plus_midpoint_to_vwap_impact",
        },
        "archive_provenance": downloaded,
        "assets": assets,
        "feasibility_decision": {
            "data_pipeline_feasible": feasible,
            "supports_full_cost_calibration": False,
            "supports_new_factor_batch": False,
            "next_requirement": "expand_to_multiple_predeclared_regime_days_before_calibrating_cost_or_freezing_a_microstructure_factor",
        },
        "limitations": [
            "One recent UTC day cannot estimate a stable long-run execution-cost distribution.",
            "Current instrument contract metadata is used for a recent historical day; older samples require point-in-time contract specifications.",
            "Market-order impact assumes immediate visible-book execution and excludes latency, queueing, hidden liquidity, rejects, and outages.",
            "Effective spread uses the latest preceding reconstructed midpoint and OKX aggressor side.",
            "The pilot does not test a factor sign, portfolio rule, or strategy return.",
        ],
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# OKX Historical L2 Feasibility Pilot",
        "",
        f"Created: {report['created_at_utc']}",
        "",
        f"Pilot date: `{report['pilot_date']}` (UTC)",
        f"Sample interval: `{report['sample_interval_ms'] / 1000:g}` seconds",
        f"Current assumed one-way cost: `{report['current_backtest_cost_model']['all_in_bps_one_way']:.2f}` bps",
        "",
        "## Decision",
        "",
        f"- Data pipeline feasible: `{report['feasibility_decision']['data_pipeline_feasible']}`",
        "- Full cost calibration supported: `False`",
        "- New factor batch supported: `False`",
        "",
        "This is a bounded schema and executable-cost feasibility check, not a",
        "factor result. Multiple predeclared market-regime days are required",
        "before these values can calibrate a strategy cost model.",
        "",
        "## Asset Results",
        "",
        "| Asset | Coverage | Median quoted spread | Volume-weighted one-way effective slippage | Median 5bps bid depth | 100 USDT buy all-in median / p95 | 10k USDT buy all-in median / p95 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for inst_id, asset in report["assets"].items():
        impact = asset["market_order_impact_bps"]
        lines.append(
            "| "
            + " | ".join(
                [
                    inst_id,
                    f"{asset['sampling']['coverage_fraction']:.2%}",
                    f"{asset['quoted_spread_bps'].get('median', float('nan')):.4f} bps",
                    f"{asset['effective_spread_bps'].get('quote_notional_weighted_one_way_slippage_bps', float('nan')):.4f} bps",
                    f"{asset['depth_usdt']['5']['bid'].get('median', float('nan')):.2f} USDT",
                    f"{impact['100']['buy'].get('median', float('nan')) + report['current_backtest_cost_model']['fee_bps_one_way']:.4f} / {impact['100']['buy'].get('p95', float('nan')) + report['current_backtest_cost_model']['fee_bps_one_way']:.4f} bps",
                    f"{impact['10000']['buy'].get('median', float('nan')) + report['current_backtest_cost_model']['fee_bps_one_way']:.4f} / {impact['10000']['buy'].get('p95', float('nan')) + report['current_backtest_cost_model']['fee_bps_one_way']:.4f} bps",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "The current 7 bps model is compared with a taker fee plus visible-book",
            "midpoint-to-VWAP impact. It does not include latency or order rejection.",
        ]
    )
    lines.extend(
        [
            "",
            "## Interpretation Limits",
            "",
            *[f"- {item}" for item in report["limitations"]],
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a bounded OKX historical L2 pilot")
    parser.add_argument("--date", type=date.fromisoformat, default=DEFAULT_PILOT_DATE)
    parser.add_argument("--instruments", nargs="+", default=list(DEFAULT_INSTRUMENTS))
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(config.CACHE_DIR) / "okx_l2_pilot",
    )
    parser.add_argument("--sample-seconds", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    if args.sample_seconds <= 0:
        raise ValueError("sample_seconds_must_be_positive")

    report = run_pilot(
        pilot_date=args.date,
        inst_ids=args.instruments,
        cache_dir=args.cache_dir,
        sample_interval_ms=args.sample_seconds * 1000,
    )
    output = args.output or Path(config.LOG_DIR) / f"okx_l2_pilot_{report['created_at_utc']}.json"
    markdown = args.markdown_output or Path(config.LOG_DIR) / f"okx_l2_pilot_{report['created_at_utc']}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, markdown)
    print(f"WROTE {output}")
    print(f"WROTE {markdown}")
    print(
        "DATA_PIPELINE_FEASIBLE",
        report["feasibility_decision"]["data_pipeline_feasible"],
    )


if __name__ == "__main__":
    main()
