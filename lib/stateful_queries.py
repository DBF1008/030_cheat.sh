"""
Support for the stateful queries
"""

import cache


def save_query(client_id, query, tenant=None):
    """
    Save the last query `query` for the client `client_id`
    """
    cache.put("l:%s" % client_id, query, tenant=tenant)


def last_query(client_id, tenant=None):
    """
    Return the last query for the client `client_id`
    """
    return cache.get("l:%s" % client_id, tenant=tenant)


def clear_last(tenant=None):
    """
    Delete all last-query entries for the given tenant.
    """
    return cache.delete_pattern("l:*", tenant=tenant)
