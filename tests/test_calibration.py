import numpy as np

from recommender.ranking.calibration import calibration_bins, expected_calibration_error


def test_calibration_bins_have_predicted_close_to_observed_when_truly_calibrated():
    rng = np.random.default_rng(0)
    n = 20000
    # Predicted probability IS the true probability used to draw labels --
    # a genuinely well-calibrated case by construction.
    y_pred = rng.uniform(0.01, 0.5, size=n)
    y_true = rng.binomial(1, y_pred)

    bins = calibration_bins(y_true, y_pred, n_bins=10)

    assert len(bins) == 10
    assert (bins["mean_predicted"] - bins["observed_rate"]).abs().max() < 0.03


def test_expected_calibration_error_is_small_for_a_truly_calibrated_model():
    rng = np.random.default_rng(1)
    n = 20000
    y_pred = rng.uniform(0.01, 0.5, size=n)
    y_true = rng.binomial(1, y_pred)

    ece = expected_calibration_error(y_true, y_pred, n_bins=10)

    assert ece < 0.02


def test_expected_calibration_error_is_large_for_systematically_overconfident_predictions():
    rng = np.random.default_rng(2)
    n = 20000
    true_prob = rng.uniform(0.01, 0.3, size=n)
    y_true = rng.binomial(1, true_prob)
    # Predictions are always 3x the true probability -- a clear,
    # deliberate miscalibration (systematic overconfidence).
    y_pred = np.clip(true_prob * 3, 0, 1)

    ece = expected_calibration_error(y_true, y_pred, n_bins=10)

    assert ece > 0.1


def test_bins_are_equal_frequency_not_equal_width():
    rng = np.random.default_rng(3)
    # Predictions clustered in a narrow low range -- equal-width bins would
    # leave most buckets empty; equal-frequency must still split evenly.
    y_pred = rng.uniform(0.01, 0.06, size=5000)
    y_true = rng.binomial(1, y_pred)

    bins = calibration_bins(y_true, y_pred, n_bins=5)

    counts = bins["count"].to_numpy()
    assert counts.min() > 0
    assert counts.max() / counts.min() < 1.5  # roughly equal-sized groups
