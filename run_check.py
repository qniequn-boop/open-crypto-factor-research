import sys, os, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '.')

print('=== DEPS ===')
import pandas, numpy, scipy, requests
print('pandas', pandas.__version__, 'numpy', numpy.__version__, 'scipy', scipy.__version__)

print()
print('=== DSL TESTS ===')
from tests import test_dsl
tests = [test_dsl.test_basic_parse, test_dsl.test_complex_expr, test_dsl.test_no_lookahead,
         test_dsl.test_field_reference, test_dsl.test_arithmetic, test_dsl.test_conditional,
         test_dsl.test_syntax_error, test_dsl.test_illegal_operator, test_dsl.test_max_depth,
         test_dsl.test_all_operators]
fail = 0
for t in tests:
    try: t()
    except Exception as e: print('FAIL:', t.__name__, '->', e); fail += 1

print()
print('=== BACKTEST TESTS ===')
from tests import test_backtest
tests2 = [test_backtest.test_backtest_basic, test_backtest.test_position_shift,
          test_backtest.test_no_future_function, test_backtest.test_cost_impact,
          test_backtest.test_sharpe_zero_signal, test_backtest.test_max_drawdown,
          test_backtest.test_sign_function, test_backtest.test_annualized_sharpe]
for t in tests2:
    try: t()
    except Exception as e: print('FAIL:', t.__name__, '->', e); fail += 1

print()
print('=== OVERFIT TESTS ===')
from tests import test_overfit
tests3 = [test_overfit.test_check_oos, test_overfit.test_walk_forward,
          test_overfit.test_param_sensitivity, test_overfit.test_dsr,
          test_overfit.test_pbo, test_overfit.test_crowding, test_overfit.test_full_check_noise]
for t in tests3:
    try: t()
    except Exception as e: print('FAIL:', t.__name__, '->', e); fail += 1

print()
print('RESULT:', fail, 'failures')
