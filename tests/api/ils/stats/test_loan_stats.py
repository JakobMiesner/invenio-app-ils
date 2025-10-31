def test_loan_request_availability():
    """Test that the availability of an item during loan request gets indexed to the loan."""

    # maybe also test that the information does not get lost when the loan proceeds further down the transition chain (e.g. checking)
    pass

def test_loan_stats_histogram():
    """Test the loan histogram endpoint."""

    # Test aggregation and group by works as intended. Maybe try combinations of group bys and aggregations and see if the result is as expected.
    pass

def test_loan_stats_permissions():
    """Test that only certain users can access the loan histogram endpoint."""
    pass
