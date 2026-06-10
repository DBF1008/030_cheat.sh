"""
Parse query arguments.

Delegates to QueryPlan for the actual parsing logic.
The parse_args() function is kept for backward compatibility.
"""


def parse_args(args):
    """
    Parse arguments and options.
    Replace short options with their long counterparts.

    NOTE: This function is kept for backward compatibility.
    New code should use QueryPlan.from_request() instead.
    """
    from query_plan import QueryPlan

    plan = QueryPlan()
    plan._parse_query_params(args)
    return plan.to_options_dict()
