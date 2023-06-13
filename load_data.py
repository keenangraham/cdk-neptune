import requests

from rdf2g import setup_graph


DEFAULT_LOCAL_CONNECTION_STRING = "ws://localhost:8182/gremlin"

g = setup_graph(DEFAULT_LOCAL_CONNECTION_STRING)


def is_link(k, terms):
    context = terms['@context'][k]
    result = '@type' in context and context['@type'] == '@id'
    return result


def clear_graph(g):
    g.V().drop().iterate()


def get_node(id_, g):
    nodes = g.V().has('@id', id_).toList()
    if not nodes:
        return None
    return nodes[-1]


def make_node(id_, type_, g):
    nodes = g.V().has('@id', id_).toList()
    if not nodes:
        node = g.addV(type_).property('@id', id_).next()
    else:
        node = nodes[-1]
    return node


def add_property(node, key, value, g):
    g.V(node).property(key, value).next()


def link_nodes(node1, node2, edge_name, g):
    g.V(node1).addE(edge_name).to(node2).iterate()


def load_node(d, g):
    make_node(d['@id'], d['@type'][0], g)


def load_properties(d, terms, g):
    node1 = get_node(d['@id'], g)
    for k, v in d.items():
        if k in ['@id', '@type', 'audit']:
            continue
        if not isinstance(v, list):
                v = [v]
        if is_link(k, terms):
            for vv in v:
                node2 = get_node(vv, g)
                if node2 is None:
                    print('No Node found for', vv)
                    print(f'Making {k} property instead of link')
                    add_property(node1, k, vv, g)
                else:
                    link_nodes(node1, node2, k, g)
        else:
            for vv in v:
                if isinstance(vv, dict):
                    print('FOUND dict, skipping', k, vv)
                    continue
                add_property(node1, k, vv, g)


def load_data(data, terms, g):
    for d in data:
        load_node(d, g)
    for d in data:
        load_properties(d, terms, g)


def get_terms():
    return requests.get('https://api.data.igvf.org/terms/').json()


def get_data():
    return requests.get('https://api.data.igvf.org/search/?type=Item&frame=object&limit=all').json()['@graph']
