# Copyright 2018 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from collections import namedtuple
import itertools as it
from six.moves import reduce

from .util import unzip2, concatenate, partial, safe_map

map = safe_map


def tree_map(f, tree):
  """Map a function over a pytree to produce a new pytree.

  Args:
    f: function to be applied at each leaf.
    tree: a pytree to be mapped over.

  Returns:
    A new pytree with the same structure as `tree` but with the value at each
    leaf given by `f(x)` where `x` is the value at the corresponding leaf in
    `tree`.
  """
  node_type = node_types.get(type(tree))
  if node_type:
    children, node_spec = node_type.to_iterable(tree)
    new_children = [tree_map(f, child) for child in children]
    return node_type.from_iterable(node_spec, new_children)
  else:
    return f(tree)

def tree_multimap(f, tree, *rest):
  """Map a multi-input function over pytree args to produce a new pytree.

  Args:
    f: function that takes `1 + len(rest)` arguments, to be applied at the
      corresponding leaves of the pytrees.
    tree: a pytree to be mapped over, with each leaf providing the first
      positional argument to `f`.
    *rest: a tuple of pytrees, each with the same structure as `tree`.

  Returns:
    A new pytree with the same structure as `tree` but with the value at each
    leaf given by `f(x, *xs)` where `x` is the value at the corresponding leaf
    in `tree` and `xs` is the tuple of values at corresponding leaves in `rest`.
  """
  # equivalent to prefix_multimap(f, tree_structure(tree), tree, *rest)
  node_type = node_types.get(type(tree))
  if node_type:
    children, node_spec = node_type.to_iterable(tree)
    all_children = [children]
    for other_tree in rest:
      other_node_type = node_types.get(type(other_tree))
      # TODO(mattjj): enable this check
      # if node_type != other_node_type:
      #   raise TypeError('Mismatch: {} != {}'.format(other_node_type, node_type))
      other_children, other_node_data = node_type.to_iterable(other_tree)
      if other_node_data != node_spec:
        raise TypeError('Mismatch: {} != {}'.format(other_node_data, node_spec))
      all_children.append(other_children)

    new_children = [tree_multimap(f, *xs) for xs in zip(*all_children)]
    return node_type.from_iterable(node_spec, new_children)
  else:
    return f(tree, *rest)

def prefix_multimap(f, treedef, tree, *rest):
  """Like tree_multimap but only maps down through a tree prefix."""
  if treedef is leaf:
    return f(tree, *rest)
  else:
    node_type = node_types.get(type(tree))
    if node_type != treedef.node_type:
      raise TypeError('Mismatch: {} != {}'.format(treedef.node_type, node_type))
    children, node_data = node_type.to_iterable(tree)
    if node_data != treedef.node_data:
      raise TypeError('Mismatch: {} != {}'.format(treedef.node_data, node_data))
    all_children = [children]
    for other_tree in rest:
      other_children, other_node_data = node_type.to_iterable(other_tree)
      if other_node_data != node_data:
        raise TypeError('Mismatch: {} != {}'.format(other_node_data, node_data))
      all_children.append(other_children)
    all_children = zip(*all_children)

    new_children = [prefix_multimap(f, td, *xs)
                    for td, xs in zip(treedef.children, all_children)]
    return node_type.from_iterable(node_data, new_children)

def tree_mimomap(f, tree, *rest):
  """Map a multi-input tuple-output over pytree args to form a tuple of pytrees.

  Args:
    f: function that takes `1 + len(rest)` arguments and returns a tuple, to be
      applied at the corresponding leaves of the pytrees.
    tree: a pytree to be mapped over, with each leaf providing the first
      positional argument to `f`.
    *rest: a tuple of pytrees, each with the same structure as `tree`.

  Returns:
    A tuple of pytrees with length given by the length of the output of `f` and
    with each pytree element having the same structure as `tree`.
  """
  flat, treedef = tree_flatten(tree)
  rest_flat, treedefs = unzip2(map(tree_flatten, rest))
  if not all(td == treedef for td in treedefs):
    td = next(td for td in treedefs if td != treedef)
    raise TypeError('Mismatch: {} != {}'.format(treedef, td))
  out_flat = zip(*map(f, flat, *rest_flat))
  return tuple(map(partial(tree_unflatten, treedef), out_flat))


def tree_reduce(f, tree):
  flat, _ = tree_flatten(tree)
  return reduce(f, flat)


def tree_all(tree):
  flat, _ = tree_flatten(tree)
  return all(flat)


def process_pytree(process_node, tree):
  return walk_pytree(process_node, lambda x: x, tree)


def walk_pytree(f_node, f_leaf, tree):
  node_type = node_types.get(type(tree))
  if node_type:
    children, node_spec = node_type.to_iterable(tree)
    proc_children, child_specs = unzip2([walk_pytree(f_node, f_leaf, child)
                                         for child in children])
    tree_def = PyTreeDef(node_type, node_spec, child_specs)
    return f_node(proc_children), tree_def
  else:
    return f_leaf(tree), leaf


def build_tree(treedef, xs):
  if treedef is leaf:
    return xs
  else:
    # We use 'iter' for clearer error messages
    children = map(build_tree, iter(treedef.children), iter(xs))
    return treedef.node_type.from_iterable(treedef.node_data, children)


tree_flatten = partial(walk_pytree, concatenate, lambda x: [x])

def tree_unflatten(treedef, xs):
  return _tree_unflatten(iter(xs), treedef)

def _tree_unflatten(xs, treedef):
  if treedef is leaf:
    return next(xs)
  else:
    children = map(partial(_tree_unflatten, xs), treedef.children)
    return treedef.node_type.from_iterable(treedef.node_data, children)


def tree_transpose(outer_treedef, inner_treedef, pytree_to_transpose):
  flat, treedef = tree_flatten(pytree_to_transpose)
  expected_treedef = _nested_treedef(inner_treedef, outer_treedef)
  if treedef != expected_treedef:
    raise TypeError("Mismatch\n{}\n != \n{}".format(treedef, expected_treedef))

  inner_size = _num_leaves(inner_treedef)
  outer_size = _num_leaves(outer_treedef)
  flat = iter(flat)
  lol = [[next(flat) for _ in range(inner_size)] for __ in range(outer_size)]
  transposed_lol = zip(*lol)
  subtrees = map(partial(tree_unflatten, outer_treedef), transposed_lol)
  return tree_unflatten(inner_treedef, subtrees)

def _num_leaves(treedef):
  return 1 if treedef is leaf else sum(map(_num_leaves, treedef.children))

def _nested_treedef(inner, outer):
  # just used in tree_transpose error checking
  if outer is leaf:
    return inner
  else:
    children = map(partial(_nested_treedef, inner), outer.children)
    return PyTreeDef(outer.node_type, outer.node_data, tuple(children))


def tree_structure(tree):
  _, spec = process_pytree(lambda _: None, tree)
  return spec


class PyTreeDef(object):
  def __init__(self, node_type, node_data, children):
    self.node_type = node_type
    self.node_data = node_data
    self.children = children

  def __repr__(self):
    if self.node_data is None:
      data_repr = ""
    else:
      data_repr = "[{}]".format(self.node_data)

    return "PyTree({}{}, [{}])".format(self.node_type.name, data_repr,
                                     ','.join(map(repr, self.children)))

  def __hash__(self):
    return hash((self.node_type, self.node_data, tuple(self.children)))

  def __eq__(self, other):
    if other is leaf:
      return False
    else:
      return (self.node_type == other.node_type and
              self.node_data == other.node_data and
              self.children == other.children)

  def __ne__(self, other):
    return not self == other


class PyLeaf(object):
  def __repr__(self):
    return '*'

leaf = PyLeaf()

def dict_to_iterable(xs):
  keys = tuple(sorted(xs.keys()))
  return tuple(map(xs.get, keys)), keys

class NodeType(object):
  def __init__(self, name, to_iterable, from_iterable):
    self.name = name
    self.to_iterable = to_iterable
    self.from_iterable = from_iterable

node_types = {}

def register_pytree_node(py_type, to_iterable, from_iterable):
  assert py_type not in node_types
  node_types[py_type] = NodeType(str(py_type), to_iterable, from_iterable)

register_pytree_node(tuple, lambda xs: (xs, None), lambda _, xs: tuple(xs))
register_pytree_node(list, lambda xs: (tuple(xs), None), lambda _, xs: list(xs))
register_pytree_node(dict, dict_to_iterable, lambda keys, xs: dict(zip(keys, xs)))
register_pytree_node(type(None), lambda z: ((), None), lambda _, xs: None)
