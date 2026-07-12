from mini_store.loyalty import points_earned


def test_gold_exactly_at_threshold_no_bonus():
    # threshold is strict > 100, so exactly 100 gets no bonus
    assert points_earned(100.0, "gold") == 200


def test_gold_just_over_threshold_bonus():
    assert points_earned(101.0, "gold") == 252  # 101*2 + 50


def test_unknown_tier_defaults_to_one_x_no_bonus():
    assert points_earned(500.0, "bronze") == 500
