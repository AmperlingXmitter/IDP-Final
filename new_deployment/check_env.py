# =============================================================================
#  ENVIRONMENT / MODEL CHECK  -  deployment/check_env.py
#  Run this FIRST on any new machine (Windows / Pi) to confirm it can load the
#  models before you wire it into an app.
#
#    python check_env.py
#
#  It prints the TF/Keras version, checks the model files exist, and actually
#  loads both models (the real deployment test). Exit code 0 = good to deploy.
# =============================================================================
import os, sys
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # use LOCAL copies

import tensorflow as tf
try:
    import keras
    KVER = keras.__version__
except Exception:
    KVER = tf.keras.__version__
import config as C

LINE = "=" * 56


def _check(name, fn):
    try:
        fn()
        print(f"  [ OK ]  {name}")
        return True
    except Exception as e:
        first = str(e).splitlines()[0] if str(e) else ""
        print(f"  [FAIL]  {name}")
        print(f"          {type(e).__name__}: {first}")
        return False


def main():
    print(LINE)
    print(f"  TensorFlow {tf.__version__}   |   Keras {KVER}")
    print(f"  Folder: {C.ROOT}")
    print(LINE)

    sev, seg = C.model_path("severity"), C.SEG_MODEL
    print(f"  severity model file : {'found' if os.path.exists(sev) else 'MISSING'}")
    print(f"  segment  model file : {'found' if os.path.exists(seg) else 'MISSING'}")
    print("-" * 56)
    print("  Loading models (the real deployment test):")

    import predict_severity_class as pc
    import segment_wound_size as sw
    ok1 = _check("severity classifier  (predict_severity_class)", pc._get_model)
    ok2 = _check("wound segmentation    (segment_wound_size)", sw._get_model)

    print(LINE)
    if ok1 and ok2:
        print("  RESULT: PASS - this machine can run both models. Good to deploy.")
        return 0
    print("  RESULT: FAIL - a model did not load.")
    print("  If the error is 'expected N variables, received 0' or")
    print("  'No module named keras.src.engine', it is a TF/Keras VERSION skew:")
    print("  install the SAME tensorflow version that saved the models")
    print("  (this project pins  tensorflow==2.15.1 ).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
