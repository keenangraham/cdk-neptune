import os

import requests

from rdf2g import setup_graph


DEFAULT_LOCAL_CONNECTION_STRING = "ws://localhost:8182/gremlin"


def get_g(endpoint=DEFAULT_LOCAL_CONNECTION_STRING):
    return setup_graph(DEFAULT_LOCAL_CONNECTION_STRING)


def is_link(k, terms):
    if k in ['term_id', 'dbxrefs', 'treatment_term_id', 'url', 'downloaded_url', 'source_url']:
        return False
    if k not in terms['@context']:
        print(f'{k} not found in terms context, not a link')
        return False
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
    return make_node(d['@id'], d['@type'][0], g)


def handle_attachment(node1, vv, d, terms, g):
    print('Found attachment, making new node')
    vv['@type'] = ['Attachment']
    vv['@id'] = vv['md5sum']
    attachment_node = load_node(vv, g)
    link_nodes(node1, attachment_node, 'attachment', g)
    load_properties(vv, terms, g)


def handle_gene_location(node1, vv, g):
    assembly = vv['assembly']
    start_key = f'start_{assembly}'
    end_key = f'end_{assembly}'
    chromosome_key = f'chromosome_{assembly}'
    add_property(node1, start_key, vv['start'], g)
    add_property(node1, end_key, vv['end'], g)
    add_property(node1, chromosome_key, vv['chromosome'], g)


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
                    if k == 'attachment':
                        handle_attachment(node1, vv, d, terms, g)
                        continue
                    if k == 'locations':
                        handle_gene_location(node1, vv, g)
                        continue
                    if k == 'layout':
                        print('skipping page layout')
                        continue
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


def get_data(url='https://api.data.igvf.org/search/?type=Item&frame=object&limit=all', auth=None):
    r = requests.get(url, auth=auth)
    return r.json()['@graph']


def clear_graph_except_genes(g):
    from gremlin_python.process.graph_traversal import __
    g.V().not_(__.hasLabel('Gene')).drop().iterate()


def quick_load():
    g = get_g(f'wss://{os.environ[NEPTUNE_ENDPOINT]}:8182/gremlin')
    url = 'https://api.data.igvf.org/search/?type=Item&type!=Gene&frame=object&limit=all'
    auth = (os.environ['IGVF_API_KEY'], os.environ['IGVF_API_SECRET'])
    data = get_data(url, auth)
    terms = get_terms()
    clear_graph_except_genes(g)
    load_data(data, terms, g)


def full_load():
    g = get_g(f'wss://{os.environ[NEPTUNE_ENDPOINT]}:8182/gremlin')
    url = 'https://api.data.igvf.org/search/?type=Item&frame=object&limit=all'
    auth = (os.environ['IGVF_API_KEY'], os.environ['IGVF_API_SECRET'])
    data = get_data(url, auth)
    terms = get_terms()
    clear_graph(g)
    load_data(data, terms, g)
