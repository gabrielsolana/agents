def approximate_pi(num_terms: int = 1_000_000) -> float:
    total = 0.0
    sign = 1.0
    denominator = 1.0

    for _ in range(num_terms):
        total += sign / denominator
        sign = -sign
        denominator += 2.0

    return total * 4.0


if __name__ == "__main__":
    pi_estimate = approximate_pi()
    print(pi_estimate)
