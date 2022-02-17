# -*- coding: utf-8 -*-
"""
A module for visualising ontologies using graphviz.
"""
import os
import re
import warnings
import tempfile
import xml.etree.ElementTree as ET

import owlready2
import graphviz

from .utils import asstring
from .ontology import get_ontology, NoSuchLabelError

typenames = owlready2.class_construct._restriction_type_2_label



def getlabel(e):
    """Returns the label of entity `e`."""
    if hasattr(e, 'label'):
        return e.label.first()
    elif hasattr(e, '__name__'):
        return e.__name__
    elif hasattr(e, 'name'):
        return str(e.name)
    else:
        return repr(e)



class OntoGraph:
    """Class for visualising an ontology.

        Parameters
        ----------
        ontology : emmo.Ontology instance
            Ontology to visualize.
        root : None | string | owlready2.ThingClass instance
            Name or owlready2 entity of root node to plot subgraph
            below.  If `root` is None, all classes will be included in the
            subgraph.
        leafs : None | sequence
            A sequence of leaf node names for generating sub-graphs.
        relations : "all" | str | None | sequence
            Sequence of relations to visualise.  If "all", means to include
            all relations.
        style : None | dict | "default"
            A dict mapping the name of the different graphical elements
            to dicts of dot graph attributes. Supported graphical elements
            include:
              - graphtype : "Digraph" | "Graph"
              - graph : graph attributes (G)
              - class : nodes for classes (N)
              - defined_class : nodes for defined classes (N)
              - class_construct : nodes for class constructs (N)
              - individual : nodes for invididuals (N)
              - object_property : nodes for object properties (N)
              - data_property : nodes for data properties (N)
              - annotation_property : nodes for annotation properties (N)
              - is_a : edges for is_a relations (E)
              - equivalent_to : edges for equivalent_to relations (E)
              - disjoint_with : edges for disjoint_with relations (E)
              - inverse_of : edges for inverse_of relations (E)
              - default_relation : default edges relations and restrictions (E)
              - relations : dict of styles for different relations (E)
              - default_dataprop : default edges for data properties (E)
            If style is None or "default", the default style is used.
            See https://www.graphviz.org/doc/info/attrs.html
        edgelabels : bool | dict
            Whether to add labels to the edges of the generated graph.
            It is also possible to provide a dict mapping the
            full labels (with cardinality stripped off for restrictions)
            to some abbriviations.
        addnodes : bool
            Whether to add missing target nodes in relations.
        addconstructs : bool
            Whether to add nodes representing class constructs.
        parents : bool | str
            Whether to include parent nodes.  If `parents` is a string,
            only parent nodes down to the given name will included.
        graph : None | pydot.Dot instance
            Graphviz Digraph object to plot into.  If None, a new graph object
            is created using the keyword arguments.
        kwargs :
            Passed to graphviz.Digraph.
    """
    _default_style = {
        'graphtype': 'Digraph',
        'graph': {
            'rankdir': 'BT', 'fontsize': '8',
            # 'fontname': 'Bitstream Vera Sans', 'splines': 'ortho',
        },
        'class': {
            'style': 'filled',
            'fillcolor': '#ffffcc',
        },
        'defined_class': {
            'style': 'filled',
            'fillcolor': '#ffc880',
        },
        'class_construct': {
            'shape': 'box',
            'style': 'filled',
            'fillcolor': 'gray',
        },
        'individual': {
            'shape': 'diamond',
            'style': 'filled',
            'fillcolor': '#874b82',
            'fontcolor': 'white',
        },
        'object_property': {
            'shape': 'box',
            'style': 'filled',
            'fillcolor': '#0079ba',
            'fontcolor': 'white',
        },
        'data_property': {
            'shape': 'box',
            'style': 'filled',
            'fillcolor': 'green',
        },
        'annotation_property': {
            'shape': 'box',
            'style': 'filled',
            'fillcolor': 'orange',
        },
        'is_a': {'arrowhead': 'empty'},
        'equivalent_to': {'color': 'green3'},
        'disjoint_with': {'color': 'red', 'constraint': 'false'},
        'inverse_of': {'color': 'orange', },
        'default_relation': {'color': 'olivedrab', 'constraint': 'false'},
        'relations': {
            'disconnected': {'color': 'red', 'style': 'dashed'},
            #'encloses': {'color': 'red', 'arrowtail': 'diamond',
            #             'dir': 'back'},
            #'hasPart': {'color': 'red', 'arrowtail': 'diamond',
            #                     'dir': 'back', 'style': 'dashed'},
            'encloses': {'color': 'blue'},
            'hasPart': {'color': 'blue', 'style': 'dashed'},
            'hasReferenceUnit': {'color': 'magenta'},
            'hasSign': {'color': 'orange', 'style': 'dotted'},
            'hasProperty': {'color': 'orange'},
        },
        'default_dataprop': {'color': 'green', 'constraint': 'false'},
    }

    def __init__(self, ontology, root=None, leafs=None,
                 relations='is_a', style=None, edgelabels=True,
                 addnodes=False, addconstructs=False,
                 parents=False, graph=None, **kwargs):
        if style is None or style == 'default':
            style = self._default_style
        if graph is None:
            graphtype = style.get('graphtype', 'Digraph')
            dotcls = getattr(graphviz, graphtype)
            graph_attr = kwargs.pop('graph_attr', {})
            for k, v in style.get('graph', {}).items():
                graph_attr.setdefault(k, v)
            self.dot = dotcls(graph_attr=graph_attr, **kwargs)
            self.nodes = set()
            self.edges = set()
        else:
            if ontology != graph.ontology:
                ValueError(
                    'the same ontology must be used when extending a graph')
            self.dot = graph.dot
            self.nodes = graph.nodes
            self.edges = graph.edges

        self.ontology = ontology
        self.relations = set(
            [relations] if isinstance(relations, str) else relations)
        self.style = style
        self.edgelabels = edgelabels
        self.addnodes = addnodes
        self.addconstructs = addconstructs

        if root:
            self.add_branch(
                root, leafs,
                relations=relations, edgelabels=edgelabels,
                addnodes=addnodes, addconstructs=addconstructs)
        if parents:
            self.add_parent(
                parents,
                relations=relations, edgelabels=edgelabels,
                addnodes=addnodes, addconstructs=addconstructs)

    def add_branch(self, root, leafs=None, include_leafs=True,
                   relations='is_a', style=None, edgelabels=True,
                   addnodes=False, addconstructs=False, **attrs):
        """Adds branch under `root` ending at any entiry included in the
        sequence `leafs`.  If `include_leafs` is true, leafs classes are
        also included."""
        if leafs is None:
            leafs = ()
        classes = self.ontology.get_branch(
            root=root, leafs=leafs, include_leafs=include_leafs)
        self.add_nodes(classes, **attrs)
        self.add_edges(
            relations=relations, edgelabels=edgelabels,
            addnodes=addnodes, addconstructs=addconstructs, **attrs)

    def add_parents(self, name, levels=None, relations=None,
                    edgelabels=None, addnodes=False, addconstructs=False,
                    **attrs):
        """Add `levels` levels of parents of entity `name`."""
        pass

    def add_node(self, name, **attrs):
        """Add node with given name. `attrs` are graphviz node attributes."""
        e = self.ontology[name] if isinstance(name, str) else name
        label = getlabel(e)
        if label not in self.nodes:
            kw = self.get_node_attrs(e, attrs)
            kw.setdefault('URL', e.iri)
            self.dot.node(label, label=label, **kw)
            self.nodes.add(label)

    def add_nodes(self, names, **attrs):
        """Add nodes with given names. `attrs` are graphviz node attributes."""
        for name in names:
            self.add_node(name, **attrs)

    def add_edge(self, subject, predicate, object, edgelabel=None, **attrs):
        """Add edge corresponding for ``(subject, predicate, object)``
        triplet."""
        subject = subject if isinstance(subject, str) else getlabel(subject)
        predicate = predicate if isinstance(predicate, str) else getlabel(
            predicate)
        object = object if isinstance(object, str) else getlabel(object)
        if not isinstance(subject, str) or not isinstance(object, str):
            raise TypeError('`subject` and `object` must be strings')
        if subject not in self.nodes:
            raise RuntimeError('`subject` "%s" must have been added' % subject)
        if object not in self.nodes:
            raise RuntimeError('`object` "%s" must have been added' % object)
        key = (subject, predicate, object)
        if key not in self.edges:
            if edgelabel is None:
                edgelabel = self.edgelabels

            if isinstance(edgelabel, str):
                label = edgelabel
            if isinstance(edgelabel, dict):
                label = edgelabel.get(predicate, predicate)
            elif edgelabel:
                label = predicate
            else:
                label = None

            kw = self.get_edge_attrs(predicate, attrs)
            self.dot.edge(subject, object, label=label, **kw)
            self.edges.add(key)

    def add_source_edges(self, source, relations=None, edgelabels=None,
                  addnodes=None, addconstructs=None, **attrs):
        """Adds all relations originating from entity `source` who's type
        are listed in `relations`."""
        if relations is None:
            relations = self.relations
        elif isinstance(relations, str):
            relations = set([relations])
        else:
            relations = set(relations)

        edgelabels = self.edgelabels if edgelabels is None else edgelabels
        addconstructs = (
            self.addconstructs if addconstructs is None else addconstructs)

        e = self.ontology[source] if isinstance(source, str) else source
        label = getlabel(e)
        for r in e.is_a:

            # is_a
            if isinstance(r, (owlready2.ThingClass,
                              owlready2.ObjectPropertyClass)):
                if 'all' in relations or 'is_a' in relations:
                    rlabel = getlabel(r)
                    if not self.add_missing_node(r, addnodes=addnodes):
                        continue
                    if r not in e.get_parents(strict=True):
                        continue
                    self.add_edge(
                        subject=label, predicate='is_a', object=rlabel, **attrs)

            # restriction
            elif isinstance(r, owlready2.Restriction):
                rname = getlabel(r.property)
                if 'all' in relations or rname in relations:
                    rlabel = '%s %s' % (rname, typenames[r.type])
                    if isinstance(r.value, owlready2.ThingClass):
                        obj = getlabel(r.value)
                        if not self.add_missing_node(r.value, addnodes):
                            continue
                    elif isinstance(r.value, owlready2.ClassConstruct):
                        obj = self.add_class_construct(r.value)
                    pred = asstring(r, exclude_object=True)
                    self.add_edge(label, pred, obj, edgelabels, **attrs)

            # inverse
            if isinstance(r, owlready2.Inverse):
                if 'all' in relations or 'inverse' in relations:
                    rlabel = getlabel(r)
                    if not self.add_missing_node(r, addnodes=addnodes):
                        continue
                    if r not in e.get_parents(strict=True):
                        continue
                    self.add_edge(
                        subject=label, predicate='inverse', object=rlabel,
                        **attrs)



    def add_edges(self, sources=None, relations=None, edgelabels=None,
                  addnodes=None, addconstructs=None, **attrs):
        """Adds all relations originating from entities `sources` who's type
        are listed in `relations`.  If `sources` is None, edges are added
        between all current nodes."""
        if sources is None:
            sources = self.nodes
        for source in sources.copy():
            self.add_source_edges(
                source, relations=relations, edgelabels=edgelabels,
                addnodes=addnodes, addconstructs=addconstructs, **attrs)

    def add_missing_node(self, name, addnodes=None):
        """Checks if `name` corresponds to a missing node and add it if
        `addnodes` is true.

        Returns true if the node exists or is added, false otherwise."""
        addnodes = self.addnodes if addnodes is None else addnodes
        e = self.ontology[name] if isinstance(name, str) else name
        label = getlabel(e)
        if label not in self.nodes:
            if addnodes:
                self.add_node(e)
            else:
                return False
        return True

    def add_class_construct(self, c):
        """Adds class construct `c` and return its label."""
        raise NotImplementedError()

    def get_node_attrs(self, name, attrs):
        """Returns attributes for node or edge `name`.  `attrs` overrides
        the default style."""
        e = self.ontology[name] if isinstance(name, str) else name
        # class
        if isinstance(e, owlready2.ThingClass):
            if self.ontology.is_defined(e):
                kw = self.style.get('defined_class', {})
            else:
                kw = self.style.get('class', {})
        # class construct
        elif isinstance(e, owlready2.ClassConstruct):
            kw = self.style.get('class_construct', {})
        # individual
        elif isinstance(e, owlready2.Thing):
            kw = self.style.get('individual', {})
        # object property
        elif isinstance(e, owlready2.ObjectPropertyClass):
            kw = self.style.get('object_property', {})
        # data property
        elif isinstance(e, owlready2.DataPropertyClass):
            kw = self.style.get('data_property', {})
        # annotation property
        elif isinstance(e, owlready2.AnnotationPropertyClass):
            kw = self.style.get('annotation_property', {})
        else:
            raise TypeError('Unknown entity type: %r' % e)
        kw = kw.copy()
        kw.update(attrs)
        return kw

    def get_edge_attrs(self, predicate, attrs):
        """Returns attributes for node or edge `name`.  `attrs` overrides
        the default style."""
        # given type
        types = ('is_a', 'equivalent_to', 'disjoint_with', 'inverse_of')
        if predicate in types:
            kw = self.style.get(predicate, {}).copy()
        else:
            default_rel = self.style.get('default_relation', {})
            default_dprop = self.style.get('default_dataprop', {})
            name = predicate.split(None, 1)[0]
            m = re.match(r'Inverse\((.*)\)', name)
            if m:
                name, = m.groups()
            e = self.ontology[name] if isinstance(name, str) else name
            relations = self.style.get('relations', {})
            rels = set(self.ontology[r] for r in relations.keys()
                       if r in self.ontology)
            for r in e.mro():
                if r in rels:
                    break
            rattrs = relations[getlabel(r)] if r in rels else {}
            # object property
            if isinstance(e, (owlready2.ObjectPropertyClass,
                                owlready2.ObjectProperty)):
                kw = self.style.get('default_relation', {}).copy()
                kw.update(rattrs)
            # data property
            elif isinstance(e, (owlready2.DataPropertyClass,
                                owlready2.DataProperty)):
                kw = self.style.get('default_dataprop', {}).copy()
                kw.update(rattrs)
            else:
                raise TypeError('Unknown entity type: %r' % e)
        kw.update(attrs)
        return kw

    def save(self, filename, format=None, **kwargs):
        """Saves graph to `filename`.  If format is not given, it is
        inferred from `filename`."""
        base, ext = os.path.splitext(filename)
        if format is None:
            format = ext.lstrip('.')
        kwargs.setdefault('cleanup', True)
        self.dot.render(base, format=format, **kwargs)

    def view(self):
        """Shows the graph in a viewer."""
        self.dot.ui(cleanup=True)


def get_figsize(graph):
    """Returns figure size (width, height) in points of figures for the
    current pydot graph object `graph`."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpfile = os.path.join(tmpdir, 'graph.svg')
        graph.write_svg(tmpfile)
        xml = ET.parse(tmpfile)
        svg = xml.getroot()
        asfloat = lambda s: float(re.match(r'^[\d.]+', s).group())
        width = svg.attrib['width']
        height = svg.attrib['height']
        assert width.endswith('pt')  # ensure that units are in points
    return asfloat(width), asfloat(height)


def get_dependencies(iri, strip_base=None):
    """Reads `iri` and returns a dict mapping ontology names to a list of
    ontologies that they depends on.  If `strip_base` is true, the base IRI
    is stripped from ontology names."""
    onto = get_ontology(iri)
    onto.load()
    base = onto.base_iri.rstrip('#')
    modules = {}

    def setmodules(onto):
        for o in onto.imported_ontologies:
            if onto.base_iri in modules:
                modules[onto.base_iri].add(o.base_iri)
            else:
                modules[onto.base_iri] = set([o.base_iri])
            if o.base_iri not in modules:
                modules[o.base_iri] = set()
            setmodules(o)

    setmodules(onto)
    return modules


def plot_modules(iri, filename=None, format=None, show=False):
    """Plot module dependency graph."""
    modules = get_dependencies(iri)

    dot = graphviz.Digraph(comment='Module dependencies')
    dot.attr(rankdir='BT')
    dot.node_attr.update(style='filled', fillcolor='lightblue', shape='box',
                         edgecolor='blue')
    dot.edge_attr.update(arrowtail='open', dir='back')

    for iri in modules.keys():
        dot.node(iri, label=iri, URL=iri)

    for iri, deps in modules.items():
        for dep in deps:
            print(iri, '->', dep)
            dot.edge("'" + iri + "'", "'" + dep + "'")

    if filename:
        base, ext = os.path.splitext(filename)
        if format is None:
            format = ext.lstrip('.')
        dot.render(base, format=format, view=False, cleanup=True)

    if show:
        dot.view(cleanup=True)
