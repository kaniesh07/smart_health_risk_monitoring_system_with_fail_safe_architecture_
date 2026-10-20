import math


class KalmanFilter1D:
    """
    Lightweight 1-D Kalman filter for real-time sensor noise reduction.
    Runs entirely on-device -- no external dependencies.
    """
    def __init__(self, process_variance=1e-3, measurement_variance=0.1):
        self.Q = process_variance       # process noise
        self.R = measurement_variance   # measurement noise
        self.x = 0.0                    # posterior estimate
        self.P = 1.0                    # posterior error estimate
        self._initialised = False

    def update(self, measurement: float) -> float:
        if not self._initialised:
            self.x = measurement
            self._initialised = True
            return self.x

        # Predict
        x_pred = self.x
        P_pred = self.P + self.Q

        # Update
        K = P_pred / (P_pred + self.R)          # Kalman gain
        self.x = x_pred + K * (measurement - x_pred)
        self.P = (1 - K) * P_pred
        return self.x


def zscore(value: float, mean: float, std: float) -> float:
    """How many standard deviations from the personal baseline."""
    return abs(value - mean) / std if std > 0 else 0.0


def running_stats(old_mean: float, old_std: float, old_n: int, new_val: float):
    """
    Welford online algorithm: returns updated (mean, std, n).
    Used to maintain adaptive per-patient baseline without storing raw history.
    """
    n = old_n + 1
    delta = new_val - old_mean
    new_mean = old_mean + delta / n
    delta2 = new_val - new_mean
    new_var = (old_std ** 2 * old_n + delta * delta2) / n
    new_std = max(math.sqrt(new_var), 0.01)   # floor to avoid divide-by-zero
    return new_mean, new_std, n
