# btclab/data.py
# OKX鏁版嵁鎷夊彇 + parquet缂撳瓨
# 涓ユ牸鎸夌収 PROJECT_DOC.md 搂4.1

import requests
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone, timedelta
import time
import os
import io
import zipfile
import config

CACHE_DIR = Path(config.CACHE_DIR)
LOG_DIR = Path(config.LOG_DIR)
OKX_HISTORICAL_RATE_LIMIT = 0.8
OKX_REQUEST_RETRIES = 5
COIN_METRICS_BASE_URL = "https://community-api.coinmetrics.io/v4"
COIN_METRICS_ASSET_ALIASES = {"iota": "miota"}


def _request_with_retries(method: str, url: str, **kwargs) -> requests.Response:
    last_exc = None
    for attempt in range(OKX_REQUEST_RETRIES):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code not in (429, 500, 502, 503, 504):
                return resp
            last_exc = IOError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        except requests.RequestException as exc:
            last_exc = exc
        time.sleep(min(2 ** attempt, 16))
    raise IOError(f"OKX request failed after {OKX_REQUEST_RETRIES} attempts: {last_exc}")

def _cache_path(inst_id: str, bar: str, days: int) -> Path:
    return CACHE_DIR / f"{inst_id}_{bar}_{days}d.parquet"

def _spot_cache_path(inst_id: str, bar: str, days: int) -> Path:
    return CACHE_DIR / f"{inst_id}_spot_{bar}_{days}d.parquet"

def _funding_cache_path(inst_id: str, days: int) -> Path:
    return CACHE_DIR / f"{inst_id}_funding_{days}d.parquet"

def _instrument_cache_path(inst_type: str) -> Path:
    return CACHE_DIR / f"okx_{inst_type.upper()}_instruments.parquet"

def _open_interest_cache_path(inst_id: str, days: int, period: str) -> Path:
    safe_period = period.replace('/', '_')
    return CACHE_DIR / f"{inst_id}_open_interest_{safe_period}_{days}d.parquet"

def _market_cap_cache_path(inst_id: str, days: int) -> Path:
    return CACHE_DIR / f"{inst_id}_coinmetrics_market_cap_{days}d.parquet"

def coin_metrics_asset_id(inst_id: str) -> str:
    base_asset = str(inst_id).split('-')[0].lower()
    return COIN_METRICS_ASSET_ALIASES.get(base_asset, base_asset)

def swap_to_spot_inst_id(inst_id: str) -> str:
    if inst_id.endswith('-SWAP'):
        return inst_id[:-5]
    return inst_id

def fetch_okx_candles(inst_id: str, bar: str, limit: int = 300,
                      after_ts: int = None, before_ts: int = None) -> list:
    url = f"{config.OKX_BASE_URL}/api/v5/market/history-candles"
    params = {'instId': inst_id, 'bar': bar, 'limit': limit}
    if after_ts:
        params['after'] = str(after_ts)
    if before_ts:
        params['before'] = str(before_ts)

    resp = _request_with_retries("GET", url, params=params, timeout=30)
    if resp.status_code != 200:
        raise IOError(f"OKX API杩斿洖 {resp.status_code}: {resp.text}")
    data = resp.json()
    if data.get('code') != '0':
        raise IOError(f"OKX API閿欒: {data.get('msg')}")
    return data['data']

def fetch_okx_funding_rate_history(inst_id: str, limit: int = 100,
                                   after_ts: int = None, before_ts: int = None) -> list:
    url = f"{config.OKX_BASE_URL}/api/v5/public/funding-rate-history"
    params = {'instId': inst_id, 'limit': limit}
    if after_ts:
        params['after'] = str(after_ts)
    if before_ts:
        params['before'] = str(before_ts)

    resp = _request_with_retries("GET", url, params=params, timeout=30)
    if resp.status_code != 200:
        raise IOError(f"OKX funding API returned {resp.status_code}: {resp.text}")
    payload = resp.json()
    if payload.get('code') != '0':
        raise IOError(f"OKX funding API error: {payload.get('msg')}")
    return payload['data']

def fetch_okx_instruments(inst_type: str = 'SWAP') -> list:
    url = f"{config.OKX_BASE_URL}/api/v5/public/instruments"
    resp = _request_with_retries("GET", url, params={'instType': inst_type}, timeout=30)
    if resp.status_code != 200:
        raise IOError(f"OKX instruments API returned {resp.status_code}: {resp.text[:500]}")
    payload = resp.json()
    if payload.get('code') != '0':
        raise IOError(f"OKX instruments API error: {payload.get('msg')}")
    return payload.get('data') or []

def fetch_okx_open_interest_history(inst_id: str, period: str = '1D',
                                    begin_ts: int = None, end_ts: int = None,
                                    limit: int = 100) -> list:
    url = f"{config.OKX_BASE_URL}/api/v5/rubik/stat/contracts/open-interest-history"
    params = {'instId': inst_id, 'period': period, 'limit': limit}
    if begin_ts is not None:
        params['begin'] = str(begin_ts)
    if end_ts is not None:
        params['end'] = str(end_ts)
    resp = _request_with_retries("GET", url, params=params, timeout=30)
    if resp.status_code != 200:
        raise IOError(f"OKX open-interest API returned {resp.status_code}: {resp.text[:500]}")
    payload = resp.json()
    if payload.get('code') != '0':
        raise IOError(f"OKX open-interest API error: {payload.get('msg')}")
    return payload.get('data') or []

def fetch_coin_metrics_market_cap(inst_id: str, start_time: str, end_time: str) -> list:
    """Fetch daily estimated circulating market cap without padding."""
    params = {
        'assets': coin_metrics_asset_id(inst_id),
        'metrics': 'CapMrktEstUSD',
        'frequency': '1d',
        'start_time': start_time,
        'end_time': end_time,
        'page_size': 10000,
    }
    url = f"{COIN_METRICS_BASE_URL}/timeseries/asset-metrics"
    resp = _request_with_retries("GET", url, params=params, timeout=30)
    if resp.status_code != 200:
        raise IOError(f"Coin Metrics market-cap API returned {resp.status_code}: {resp.text[:500]}")
    payload = resp.json()
    if payload.get('error'):
        raise IOError(f"Coin Metrics market-cap API error: {payload['error']}")
    if payload.get('next_page_url'):
        raise IOError("Coin Metrics market-cap response unexpectedly paginated")
    return payload.get('data') or []

def fetch_okx_historical_funding_links(inst_id: str, begin_ms: int, end_ms: int) -> list:
    family = inst_id.replace('-SWAP', '')
    payload = {
        'module': '3',
        'instType': 'SWAP',
        'instQueryParam': {'instFamilyList': [family]},
        'dateQuery': {
            'dateAggrType': 'monthly',
            'begin': str(begin_ms),
            'end': str(end_ms),
        },
    }
    headers = {
        'user-agent': 'Mozilla/5.0',
        'referer': f"{config.OKX_BASE_URL}/historical-data",
        'content-type': 'application/json',
    }
    resp = None
    for attempt in range(5):
        resp = _request_with_retries(
            "POST",
            f"{config.OKX_BASE_URL}/priapi/v5/broker/public/trade-data/download-link",
            json=payload,
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 429:
            break
        time.sleep(5 * (attempt + 1))
    if resp.status_code != 200:
        raise IOError(f"OKX historical funding link API returned {resp.status_code}: {resp.text[:500]}")
    payload = resp.json()
    if payload.get('code') != '0':
        raise IOError(f"OKX historical funding link API error: {payload.get('msg')}")
    links = []
    for detail in payload.get('data', {}).get('details', []):
        for item in detail.get('groupDetails', []):
            if item.get('url'):
                links.append(item)
    return links

def _month_starts(start: datetime, end: datetime) -> list[datetime]:
    current = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    months = []
    while current <= end:
        months.append(current)
        if current.month == 12:
            current = datetime(current.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            current = datetime(current.year, current.month + 1, 1, tzinfo=timezone.utc)
    return months

def fetch_okx_historical_funding_links_chunked(inst_id: str, start: datetime, end: datetime) -> list:
    by_url = {}
    months = _month_starts(start, end)
    for month in months:
        if month.month == 12:
            next_month = datetime(month.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month = datetime(month.year, month.month + 1, 1, tzinfo=timezone.utc)
        begin_ms = int(month.timestamp() * 1000)
        end_ms = int((next_month - timedelta(milliseconds=1)).timestamp() * 1000)
        for item in fetch_okx_historical_funding_links(inst_id, begin_ms, end_ms):
            by_url[item['url']] = item
        time.sleep(OKX_HISTORICAL_RATE_LIMIT)
    return list(by_url.values())

def _candles_to_df(raw: list) -> pd.DataFrame:
    # OKX杩斿洖: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
    cols = ['ts', 'open', 'high', 'low', 'close', 'volume', 'vol_ccy', 'vol_quote', 'confirm']
    df = pd.DataFrame(raw, columns=cols)
    for col in ['open', 'high', 'low', 'close', 'volume', 'vol_quote']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['ts'] = pd.to_datetime(pd.to_numeric(df['ts']), unit='ms', utc=True)
    df = df.sort_values('ts').reset_index(drop=True)
    df = df.set_index('ts')
    return df[['open', 'high', 'low', 'close', 'volume', 'vol_quote']]

def _funding_to_df(raw: list) -> pd.DataFrame:
    df = pd.DataFrame(raw)
    if df.empty:
        return pd.DataFrame(columns=['funding_rate'])
    rate_col = 'realizedRate' if 'realizedRate' in df.columns else 'fundingRate'
    df['ts'] = pd.to_datetime(pd.to_numeric(df['fundingTime']), unit='ms', utc=True)
    df['funding_rate'] = pd.to_numeric(df[rate_col], errors='coerce')
    df = df.sort_values('ts').drop_duplicates('ts').set_index('ts')
    return df[['funding_rate']]

def _instruments_to_df(raw: list) -> pd.DataFrame:
    df = pd.DataFrame(raw)
    columns = [
        'instId', 'instType', 'instFamily', 'state', 'listTime', 'settleCcy',
        'ctVal', 'ctValCcy', 'ctType', 'ruleType', 'instCategory',
    ]
    for column in columns:
        if column not in df:
            df[column] = None
    df = df[columns].copy()
    df['list_time_ms'] = pd.to_numeric(df['listTime'], errors='coerce').astype('Int64')
    df['list_time'] = pd.to_datetime(df['list_time_ms'], unit='ms', utc=True, errors='coerce')
    df['fetched_at_utc'] = pd.Timestamp.now(tz='UTC')
    df = df.rename(
        columns={
            'instId': 'inst_id',
            'instType': 'inst_type',
            'instFamily': 'inst_family',
            'listTime': 'list_time_raw',
            'settleCcy': 'settle_ccy',
            'ctVal': 'contract_value',
            'ctValCcy': 'contract_value_ccy',
            'ctType': 'contract_type',
            'ruleType': 'rule_type',
            'instCategory': 'instrument_category',
        }
    )
    return df.sort_values('inst_id').drop_duplicates('inst_id').set_index('inst_id')

def _open_interest_to_df(raw: list) -> pd.DataFrame:
    rows = []
    for item in raw:
        if isinstance(item, dict):
            rows.append(
                {
                    'ts': item.get('ts'),
                    'open_interest_contracts': item.get('oi'),
                    'open_interest_ccy': item.get('oiCcy'),
                    'open_interest_usd': item.get('oiUsd'),
                }
            )
        elif len(item) >= 4:
            rows.append(
                {
                    'ts': item[0],
                    'open_interest_contracts': item[1],
                    'open_interest_ccy': item[2],
                    'open_interest_usd': item[3],
                }
            )
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(
            columns=['open_interest_contracts', 'open_interest_ccy', 'open_interest_usd'],
            index=pd.DatetimeIndex([], name='ts', tz='UTC'),
        )
    df['ts'] = pd.to_datetime(pd.to_numeric(df['ts']), unit='ms', utc=True)
    for column in ('open_interest_contracts', 'open_interest_ccy', 'open_interest_usd'):
        df[column] = pd.to_numeric(df[column], errors='coerce')
    return df.sort_values('ts').drop_duplicates('ts').set_index('ts')

def _coin_metrics_market_cap_to_df(raw: list) -> pd.DataFrame:
    df = pd.DataFrame(raw)
    if df.empty:
        return pd.DataFrame(
            columns=['market_cap_usd'],
            index=pd.DatetimeIndex([], name='ts', tz='UTC'),
        )
    if 'time' not in df or 'CapMrktEstUSD' not in df:
        raise ValueError("Coin Metrics market-cap response missing required fields")
    df['ts'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
    df['market_cap_usd'] = pd.to_numeric(df['CapMrktEstUSD'], errors='coerce')
    df = df.dropna(subset=['ts', 'market_cap_usd'])
    return df.sort_values('ts').drop_duplicates('ts').set_index('ts')[['market_cap_usd']]

def _historical_funding_links_to_df(links: list) -> pd.DataFrame:
    frames = []
    for item in links:
        resp = _request_with_retries("GET", item['url'], timeout=30)
        if resp.status_code != 200:
            raise IOError(f"OKX historical funding zip returned {resp.status_code}: {item.get('filename')}")
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for name in zf.namelist():
                if not name.endswith('.csv'):
                    continue
                with zf.open(name) as fh:
                    frame = pd.read_csv(fh)
                frames.append(frame)
        time.sleep(OKX_HISTORICAL_RATE_LIMIT)
    if not frames:
        return pd.DataFrame(columns=['funding_rate'])
    df = pd.concat(frames, ignore_index=True)
    df['ts'] = pd.to_datetime(pd.to_numeric(df['funding_time']), unit='ms', utc=True)
    df['funding_rate'] = pd.to_numeric(df['funding_rate'], errors='coerce')
    df = df.sort_values('ts').drop_duplicates('ts').set_index('ts')
    return df[['funding_rate']]

def load_instruments(inst_type: str = 'SWAP', force_refresh: bool = False) -> pd.DataFrame:
    cache_path = _instrument_cache_path(inst_type)
    if cache_path.exists() and not force_refresh:
        df = pd.read_parquet(cache_path)
        if 'list_time' in df and getattr(df['list_time'].dt, 'tz', None) is None:
            df['list_time'] = df['list_time'].dt.tz_localize('UTC')
        return df

    raw = fetch_okx_instruments(inst_type)
    if not raw:
        raise ValueError(f"no instrument metadata fetched: {inst_type}")
    df = _instruments_to_df(raw)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path)
    return df

def load_open_interest_history(inst_id: str, days: int = None, period: str = '1D',
                               force_refresh: bool = False) -> pd.DataFrame:
    days = days or config.HISTORY_DAYS
    cache_path = _open_interest_cache_path(inst_id, days, period)
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    if cache_path.exists() and not force_refresh:
        df = pd.read_parquet(cache_path)
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        if not df.empty and df.index.min() <= cutoff_dt + timedelta(days=7):
            return df

    all_rows = []
    end_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    cutoff_ms = int(cutoff_dt.timestamp() * 1000)
    while True:
        rows = fetch_okx_open_interest_history(
            inst_id,
            period=period,
            end_ts=end_ts,
            limit=100,
        )
        if not rows:
            break
        all_rows.extend(rows)
        oldest_ts = min(int(item.get('ts')) if isinstance(item, dict) else int(item[0]) for item in rows)
        if oldest_ts <= cutoff_ms:
            break
        if oldest_ts >= end_ts:
            break
        end_ts = oldest_ts - 1
        time.sleep(config.OKX_RATE_LIMIT)

    if not all_rows:
        raise ValueError(f"no open-interest history fetched: {inst_id} {period} {days}d")
    df = _open_interest_to_df(all_rows)
    df = df[df.index >= cutoff_dt]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path)
    return df

def load_market_cap_history(inst_id: str, days: int = None, force_refresh: bool = False) -> pd.DataFrame:
    """Load point-in-time daily estimated market cap from Coin Metrics.

    The returned daily events are not forward filled. Callers must apply an
    explicit information lag before aligning them to intraday bars.
    """
    days = days or config.HISTORY_DAYS
    cache_path = _market_cap_cache_path(inst_id, days)
    cutoff = pd.Timestamp.now(tz='UTC').floor('D') - pd.Timedelta(days=int(days))
    if cache_path.exists() and not force_refresh:
        df = pd.read_parquet(cache_path)
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        if not df.empty and df.index.min() <= cutoff + pd.Timedelta(days=7):
            return df

    start = (cutoff - pd.Timedelta(days=7)).date().isoformat()
    end = pd.Timestamp.now(tz='UTC').floor('D').date().isoformat()
    raw = fetch_coin_metrics_market_cap(inst_id, start, end)
    if not raw:
        raise ValueError(f"no Coin Metrics market-cap history fetched: {inst_id} {days}d")
    df = _coin_metrics_market_cap_to_df(raw)
    df = df.loc[df.index >= cutoff - pd.Timedelta(days=7)]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + '.tmp')
    df.to_parquet(tmp_path)
    os.replace(tmp_path, cache_path)
    return df

def load_data(inst_id: str = None, bar: str = None, days: int = None,
              force_refresh: bool = False) -> pd.DataFrame:
    inst_id = inst_id or config.INST_ID
    bar = bar or config.BAR
    days = days or config.HISTORY_DAYS

    cache_path = _cache_path(inst_id, bar, days)

    if cache_path.exists() and not force_refresh:
        df = pd.read_parquet(cache_path)
        # 纭繚 tz-aware UTC
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        return df

    # 鎷夊彇鏁版嵁 (鍒嗛〉)
    # OKX after param: return candles with ts < after_ts
    # Start from now, page backwards until we have 'days' of data
    all_candles = []
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    after_ts = now_ms

    while True:
        candles = fetch_okx_candles(inst_id, bar, limit=300, after_ts=after_ts)
        if not candles:
            break
        all_candles.extend(candles)
        # OKX returns newest-first; oldest in this batch is the cursor for next page
        oldest_ts = int(candles[-1][0])
        if oldest_ts <= cutoff_ms:
            break
        if oldest_ts >= after_ts:
            break  # no progress, avoid infinite loop
        after_ts = oldest_ts
        time.sleep(config.OKX_RATE_LIMIT)

    if not all_candles:
        raise ValueError(f"鏈媺鍙栧埌鏁版嵁: {inst_id} {bar} {days}d")

    df = _candles_to_df(all_candles)

    # 缂撳瓨
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path)

    return df


def refresh_ohlcv_cache_incremental(
    inst_id: str,
    bar: str = None,
    days: int = None,
    recent_limit: int = 300,
    spot: bool = False,
) -> pd.DataFrame:
    """Merge recent confirmed exchange bars into the long-history cache."""
    bar = bar or config.BAR
    days = days or config.HISTORY_DAYS
    request_inst_id = swap_to_spot_inst_id(inst_id) if spot else inst_id
    cache_path = (
        _spot_cache_path(request_inst_id, bar, days)
        if spot
        else _cache_path(request_inst_id, bar, days)
    )
    existing = pd.read_parquet(cache_path) if cache_path.exists() else pd.DataFrame()
    if len(existing) and existing.index.tz is None:
        existing.index = existing.index.tz_localize('UTC')
    recent_raw = fetch_okx_candles(request_inst_id, bar, limit=int(recent_limit))
    if not recent_raw:
        raise ValueError(f"no recent data fetched: {inst_id} {bar}")
    recent = _candles_to_df([row for row in recent_raw if len(row) < 9 or str(row[8]) == '1'])
    if recent.empty:
        raise ValueError(f"no confirmed recent bars fetched: {inst_id} {bar}")
    merged = pd.concat([existing, recent]).sort_index()
    merged = merged[~merged.index.duplicated(keep='last')]
    cutoff = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=int(days) + 7)
    merged = merged.loc[merged.index >= cutoff]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + '.tmp')
    merged.to_parquet(tmp_path)
    os.replace(tmp_path, cache_path)
    return merged


def refresh_funding_cache_incremental(
    inst_id: str,
    days: int = None,
    recent_limit: int = 100,
) -> pd.Series:
    """Merge recent realized funding events without forward filling."""
    days = days or config.HISTORY_DAYS
    cache_path = _funding_cache_path(inst_id, days)
    existing = pd.read_parquet(cache_path) if cache_path.exists() else pd.DataFrame(columns=['funding_rate'])
    if len(existing) and existing.index.tz is None:
        existing.index = existing.index.tz_localize('UTC')
    recent_raw = fetch_okx_funding_rate_history(inst_id, limit=int(recent_limit))
    recent = _funding_to_df(recent_raw)
    if recent.empty:
        raise ValueError(f"no recent funding events fetched: {inst_id}")
    merged = pd.concat([existing[['funding_rate']], recent]).sort_index()
    merged = merged[~merged.index.duplicated(keep='last')]
    cutoff = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=int(days) + 7)
    merged = merged.loc[merged.index >= cutoff]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + '.tmp')
    merged.to_parquet(tmp_path)
    os.replace(tmp_path, cache_path)
    return merged['funding_rate']


def refresh_open_interest_cache_incremental(
    inst_id: str,
    days: int = None,
    period: str = '1D',
    recent_limit: int = 100,
) -> pd.DataFrame:
    """Merge recent sparse open-interest observations without padding."""
    days = days or config.HISTORY_DAYS
    cache_path = _open_interest_cache_path(inst_id, days, period)
    columns = ['open_interest_contracts', 'open_interest_ccy', 'open_interest_usd']
    existing = pd.read_parquet(cache_path) if cache_path.exists() else pd.DataFrame(columns=columns)
    if len(existing) and existing.index.tz is None:
        existing.index = existing.index.tz_localize('UTC')
    recent_raw = fetch_okx_open_interest_history(inst_id, period=period, limit=int(recent_limit))
    recent = _open_interest_to_df(recent_raw)
    if recent.empty:
        raise ValueError(f"no recent open-interest events fetched: {inst_id} {period}")
    merged = pd.concat([existing[columns], recent[columns]]).sort_index()
    merged = merged[~merged.index.duplicated(keep='last')]
    cutoff = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=int(days) + 7)
    merged = merged.loc[merged.index >= cutoff]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + '.tmp')
    merged.to_parquet(tmp_path)
    os.replace(tmp_path, cache_path)
    return merged

def load_spot_data(inst_id: str = None, bar: str = None, days: int = None,
                   force_refresh: bool = False) -> pd.DataFrame:
    inst_id = inst_id or config.INST_ID
    bar = bar or config.BAR
    days = days or config.HISTORY_DAYS
    spot_inst_id = swap_to_spot_inst_id(inst_id)
    cache_path = _spot_cache_path(spot_inst_id, bar, days)

    if cache_path.exists() and not force_refresh:
        df = pd.read_parquet(cache_path)
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        return df

    all_candles = []
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    cutoff_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    after_ts = now_ms

    while True:
        candles = fetch_okx_candles(spot_inst_id, bar, limit=300, after_ts=after_ts)
        if not candles:
            break
        all_candles.extend(candles)
        oldest_ts = int(candles[-1][0])
        if oldest_ts <= cutoff_ms:
            break
        if oldest_ts >= after_ts:
            break
        after_ts = oldest_ts
        time.sleep(config.OKX_RATE_LIMIT)

    if not all_candles:
        raise ValueError(f"no spot data fetched: {spot_inst_id} {bar} {days}d")

    df = _candles_to_df(all_candles)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path)
    return df

def load_funding_rates(inst_id: str = None, days: int = None,
                       force_refresh: bool = False) -> pd.Series:
    inst_id = inst_id or config.INST_ID
    days = days or config.HISTORY_DAYS
    cache_path = _funding_cache_path(inst_id, days)
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)

    if cache_path.exists() and not force_refresh:
        df = pd.read_parquet(cache_path)
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        if not df.empty and df.index.min() <= cutoff_dt + timedelta(days=7):
            return df['funding_rate']
        print("funding cache does not cover requested history; refreshing from historical source")

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    cutoff_ms = int(cutoff_dt.timestamp() * 1000)

    # Prefer OKX's official historical-data download source; the REST funding
    # history endpoint only covers a recent window and is not enough for audits.
    try:
        links = fetch_okx_historical_funding_links_chunked(inst_id, cutoff_dt, datetime.now(timezone.utc))
        if links:
            df = _historical_funding_links_to_df(links)
            df = df[df.index >= cutoff_dt]
            if not df.empty and df.index.min() <= cutoff_dt + timedelta(days=7):
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                df.to_parquet(cache_path)
                return df['funding_rate']
            print("historical funding download did not cover the requested start date")
    except Exception as exc:
        print(f"historical funding download failed: {exc}")
        if cache_path.exists():
            df = pd.read_parquet(cache_path)
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC')
            if not df.empty and df.index.min() <= cutoff_dt + timedelta(days=7):
                return df['funding_rate']
        print("falling back to REST endpoint because no funding cache is available")

    all_rates = []
    after_ts = now_ms

    while True:
        rates = fetch_okx_funding_rate_history(inst_id, limit=100, after_ts=after_ts)
        if not rates:
            break
        all_rates.extend(rates)
        oldest_ts = min(int(item['fundingTime']) for item in rates)
        if oldest_ts <= cutoff_ms:
            break
        if oldest_ts >= after_ts:
            break
        after_ts = oldest_ts
        time.sleep(config.OKX_RATE_LIMIT)

    if not all_rates:
        raise ValueError(f"no funding data fetched: {inst_id} {days}d")

    df = _funding_to_df(all_rates)
    df = df[df.index >= (datetime.now(timezone.utc) - timedelta(days=days))]
    if df.empty or df.index.min() > cutoff_dt + timedelta(days=7):
        raise ValueError(
            f"funding history incomplete: {inst_id} requested={days}d "
            f"oldest={df.index.min() if not df.empty else None}"
        )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path)
    return df['funding_rate']

def split_data(df: pd.DataFrame, ratios: tuple = None) -> tuple:
    ratios = ratios or config.SPLIT_RATIOS
    n = len(df)
    is_end = int(n * ratios[0])
    val_end = int(n * (ratios[0] + ratios[1]))

    is_data = df.iloc[:is_end].copy()
    val_data = df.iloc[is_end:val_end].copy()
    holdout_data = df.iloc[val_end:].copy()

    return is_data, val_data, holdout_data

def get_time_ranges(df: pd.DataFrame, ratios: tuple = None) -> dict:
    ratios = ratios or config.SPLIT_RATIOS
    n = len(df)
    is_end = int(n * ratios[0])
    val_end = int(n * (ratios[0] + ratios[1]))

    return {
        'full_start': df.index[0], 'full_end': df.index[-1], 'full_bars': n,
        'is_start': df.index[0], 'is_end': df.index[is_end - 1], 'is_bars': is_end,
        'val_start': df.index[is_end], 'val_end': df.index[val_end - 1], 'val_bars': val_end - is_end,
        'holdout_start': df.index[val_end], 'holdout_end': df.index[-1], 'holdout_bars': n - val_end,
    }

# 鍒濆鍖?
CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
