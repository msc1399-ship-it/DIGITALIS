def calculate_icc(base_real, base_icc, pct):

    franchise_base = max(base_real - base_icc, 0)

    franchise_cost = franchise_base * pct

    return franchise_cost
