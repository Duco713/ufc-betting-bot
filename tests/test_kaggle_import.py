from src.importers.kaggle import norm_name
from src.scrapers.parse_utils import clean


def test_norm_name_accents_and_punctuation():
    assert norm_name("Ion Cuțelaba") == "ion cutelaba"
    assert norm_name("  Jiří  Procházka ") == "jiri prochazka"
    assert norm_name("T.J. Dillashaw") == "tj dillashaw"
    assert norm_name(None) == ""


def test_clean_handles_pandas_nan():
    assert clean(float("nan")) is None
