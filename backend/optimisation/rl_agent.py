"""
optimisation/rl_agent.py — Tabular Q-learning RL agent for dynamic price adjustment.

State: (seasonality_bucket, fiscal_quarter, stock_pressure_bucket, lag1_bucket)
Action: price multiplier index (0 = 0.8x, 19 = 1.2x default for 20-point grid)
Reward: revenue × margin_factor − penalty for constraint violations

Policy is trained offline over historical cleaned data and persisted.
At inference time, the policy outputs a RL multiplier nudge applied by the simulator.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from config import settings

# ── Hyper-parameters ──────────────────────────────────────────────────────────
ALPHA = 0.1          # Learning rate
GAMMA = 0.95         # Discount factor
EPSILON_START = 1.0  # Initial exploration rate
EPSILON_MIN = 0.05   # Minimum exploration rate
EPSILON_DECAY = 0.995
N_ACTIONS = settings.PRICE_GRID_POINTS  # 20 price points


def _discretise(value: float, n_bins: int, low: float, high: float) -> int:
    """Map a continuous value to a discrete bucket index."""
    clipped = max(low, min(high, value))
    fraction = (clipped - low) / (high - low) if high > low else 0.0
    return min(int(fraction * n_bins), n_bins - 1)


def _get_state(row: pd.Series) -> Tuple[int, int, int, int]:
    """Encode a data row into a discrete state tuple."""
    season_bucket = _discretise(float(row.get("Seasonality", 1.0)), 4, 0.5, 2.0)
    quarter = max(0, min(3, int(row.get("fiscal_quarter", 1)) - 1))
    stock_bucket = _discretise(float(row.get("stock_pressure", 0.5)), 4, 0.0, 1.0)
    lag1_bucket = _discretise(float(row.get("Lag_1", 0.0)), 5, 0.0, 500.0)
    return (season_bucket, quarter, stock_bucket, lag1_bucket)


class RLPriceAgent:
    """Tabular Q-learning agent for price action selection."""

    def __init__(self):
        self.q_table: Dict[Tuple, np.ndarray] = {}
        self.epsilon = EPSILON_START

    def _get_q(self, state: Tuple) -> np.ndarray:
        if state not in self.q_table:
            self.q_table[state] = np.zeros(N_ACTIONS)
        return self.q_table[state]

    def select_action(self, state: Tuple, explore: bool = False) -> int:
        """Epsilon-greedy action selection."""
        if explore and np.random.random() < self.epsilon:
            return np.random.randint(N_ACTIONS)
        return int(np.argmax(self._get_q(state)))

    def update(self, state: Tuple, action: int, reward: float, next_state: Tuple) -> None:
        """Q-learning update rule."""
        q = self._get_q(state)
        next_q = self._get_q(next_state)
        q[action] += ALPHA * (reward + GAMMA * np.max(next_q) - q[action])

    def decay_epsilon(self) -> None:
        self.epsilon = max(EPSILON_MIN, self.epsilon * EPSILON_DECAY)

    def action_to_multiplier(self, action: int) -> float:
        """Convert action index to price multiplier in [0.8, 1.2]."""
        actions = np.linspace(
            settings.PRICE_LOWER_BOUND, settings.PRICE_UPPER_BOUND, N_ACTIONS
        )
        return float(actions[action])

    def save(self, path: Path) -> None:
        serialisable = {
            json.dumps(list(k)): v.tolist()
            for k, v in self.q_table.items()
        }
        policy_data = {"q_table": serialisable, "epsilon": self.epsilon}
        with open(path, "w") as f:
            json.dump(policy_data, f)

    def load(self, path: Path) -> None:
        if not Path(path).exists():
            return
        with open(path, "r") as f:
            policy_data = json.load(f)
        self.q_table = {
            tuple(json.loads(k)): np.array(v)
            for k, v in policy_data.get("q_table", {}).items()
        }
        self.epsilon = policy_data.get("epsilon", EPSILON_MIN)


def train_rl_agent(df: pd.DataFrame, n_episodes: int = 5) -> RLPriceAgent:
    """
    Train the RL agent offline on historical cleaned data.
    Reward = revenue * margin_factor (simplified for offline tabular Q-learning).
    """
    agent = RLPriceAgent()
    price_grid = np.linspace(
        settings.PRICE_LOWER_BOUND, settings.PRICE_UPPER_BOUND, N_ACTIONS
    )

    for episode in range(n_episodes):
        shuffled = df.sample(frac=1, random_state=episode).reset_index(drop=True)
        for i in range(len(shuffled) - 1):
            row = shuffled.iloc[i]
            next_row = shuffled.iloc[i + 1]

            state = _get_state(row)
            next_state = _get_state(next_row)
            action = agent.select_action(state, explore=True)

            multiplier = price_grid[action]
            candidate_price = float(row.get("UnitPrice", 1.0)) * multiplier
            unit_cost = float(row.get("UnitCost", 0.0))
            demand = float(row.get("UnitsSold", 0.0))

            revenue = candidate_price * demand
            margin_pct = (candidate_price - unit_cost) / candidate_price if candidate_price > 0 else 0.0

            if margin_pct < settings.MIN_MARGIN_PCT:
                reward = -revenue * 0.5  # Penalty for margin violation
            else:
                margin_factor = min(margin_pct / settings.MIN_MARGIN_PCT, 2.0)
                reward = revenue * margin_factor

            agent.update(state, action, reward, next_state)

        agent.decay_epsilon()

    return agent


def get_rl_multiplier(agent: RLPriceAgent, row: pd.Series) -> float:
    """Get the RL-recommended price multiplier for a feature row."""
    state = _get_state(row)
    action = agent.select_action(state, explore=False)
    return agent.action_to_multiplier(action)


def load_or_create_agent(policy_path: Path) -> RLPriceAgent:
    """Load existing RL policy or create a new untrained agent."""
    agent = RLPriceAgent()
    if policy_path.exists():
        agent.load(policy_path)
    return agent
