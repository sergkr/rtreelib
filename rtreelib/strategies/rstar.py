"""
R*-Tree implementation, as described in this paper:
https://infolab.usc.edu/csci599/Fall2001/paper/rstar-tree.pdf
"""

import math
from typing import List, TypeVar, Iterable, Callable, Any, Dict
from ..rtree import RTreeBase, RTreeEntry, RTreeNode, DEFAULT_MAX_ENTRIES, EPSILON, EntryDivision, EntryOrdering
from rtreelib.models import Rect, Axis, Dimension, EntryDistribution, RStarStat
from .base import least_area_enlargement

T = TypeVar('T')


def rstar_choose_leaf(tree: RTreeBase[T], entry: RTreeEntry[T]) -> RTreeNode[T]:
    """
    Strategy used for choosing a leaf node when inserting a new entry. For choosing non-leaf nodes, the strategy is
    based on least area enlargement (same as the original Guttman implementation). For choosing leaf nodes, R*-tree uses
    minimum overlap enlargement instead.
    :param tree: R-Tree instance
    :param entry: Entry being inserted
    :return: Leaf node where the entry should be inserted. This node may or may not have the capacity for the new entry.
        If the insertion of the new node results in the node overflowing, it will be split according to the strategy
        defined by split_node.
    """
    node = tree.root
    while not node.is_leaf:
        if _are_children_leaves(node):
            e = least_overlap_enlargement(node.entries, entry.rect)
        else:
            e = least_area_enlargement(node.entries, entry.rect)
        node = e.child
    return node


def _are_children_leaves(node: RTreeNode[T]) -> bool:
    for entry in node.entries:
        if entry.child is not None:
            if entry.child.is_leaf:
                return True
    return False


def least_overlap_enlargement(entries: List[RTreeEntry[T]], rect: Rect) -> RTreeEntry[T]:
    """
    Least overlap enlargement strategy (used when inserting an entry into a leaf node).
    :param entries: Entries in the node where the insert is occurring
    :param rect: Bounding rectangle of the entry being inserted
    :return: Returns the entry from 'entries' whose bounding rectangle results in least overlap enlargement if it is
        expanded to accommodate 'rect'. In case of tie, this strategy falls back to least area enlargement.
    """
    overlaps = [overlap(e.rect, [e2.rect for e2 in without(entries, e)]) for e in entries]
    overlap_enlargements = [overlap(e.rect.union(rect), [e2.rect for e2 in without(entries, e)]) - overlaps[i]
                            for i, e in enumerate(entries)]
    min_enlargement = min(overlap_enlargements)
    indices = [i for i, v in enumerate(overlap_enlargements) if math.isclose(v, min_enlargement, rel_tol=EPSILON)]
    # If a single entry is a clear winner, choose that entry.
    if len(indices) == 1:
        return entries[indices[0]]
    else:
        # If multiple entries have the same overlap enlargement, use least area enlargement strategy as a tie-breaker.
        entries = [entries[i] for i in indices]
        return least_area_enlargement(entries, rect)


def without(items: List[T], item: T) -> List[T]:
    """Returns all items in a list except the given item."""
    return [i for i in items if i != item]


def overlap(rect: Rect, rects: List[Rect]) -> float:
    """
    Returns the total overlap area of one rectangle with respect to the others. Any common areas where multiple
    rectangles intersect will be counted multiple times.
    """
    return sum([rect.get_intersection_area(r) for r in rects])


def get_rstar_stat(entries: List[RTreeEntry[T]], min_entries: int, max_entries: int) -> RStarStat:
    """
    Calculates metrics used by the split algorithm when splitting an overflowing node. Since these metrics are used
    in multiple steps, they are calculated here once and then cached. These metrics are primarily the list of possible
    divisions of entries along each axis ('x' and 'y'), as well as dimension ('min' and 'max'). The RStarStat helper
    class also provides methods for calculating the total perimeter value along each axis.
    :param entries: List of entries in the node being split
    :param min_entries: Minimum number of entries per node
    :param max_entries: Maximum number of entries per node
    :return: Cached statistics for this list of entries
    """
    sort_divisions: Dict[EntryOrdering, List[EntryDivision]] = {}
    stat = RStarStat()
    for axis in ['x', 'y']:
        for dimension in ['min', 'max']:
            sorted_entries = tuple(sorted(entries, key=_get_sort_key(axis, dimension)))
            divisions = sort_divisions.get(sorted_entries, None)
            if divisions is None:
                divisions = get_possible_divisions(sorted_entries, min_entries, max_entries)
                sort_divisions[sorted_entries] = divisions
            for division in divisions:
                stat.add_distribution(axis, dimension, division)
    return stat


def _get_sort_key(axis: Axis, dimension: Dimension) -> Callable[[RTreeEntry[T]], Any]:
    if axis == 'x' and dimension == 'min':
        return lambda e: e.rect.min_x
    if axis == 'x' and dimension == 'max':
        return lambda e: e.rect.max_x
    if axis == 'y' and dimension == 'min':
        return lambda e: e.rect.min_y
    if axis == 'y' and dimension == 'max':
        return lambda e: e.rect.max_y


def choose_split_axis(stat: RStarStat) -> Axis:
    """
    Determines the axis perpendicular to which the entries should be split, based on the one with the smallest overall
    perimeter after determining all possible divisions of the entries that satisfy min_entries and max_entries.
    :param stat: RStarStat instance (as returned by get_rstar_stat)
    :return: Best split axis ('x' or 'y')
    """
    perimeter_x = stat.get_axis_perimeter('x')
    perimeter_y = stat.get_axis_perimeter('y')
    return 'x' if perimeter_x <= perimeter_y else 'y'


def get_possible_divisions(entries: Iterable[RTreeEntry[T]], min_entries: int, max_entries: int) -> List[EntryDivision]:
    """
    Returns a list of all possible divisions of a sorted list of entries into two groups (preserving order), where each
    group has at least min_entries number of entries.
    :param entries: List of entries, sorted by some criteria.
    :param min_entries: Minimum number of entries in each group.
    :param max_entries: Maximum number of entries in each group. It is assumed that the entries list contains one
        greater than the maximum number of entries (i.e., the entries list corresponds to a node that is now overflowing
        after the insertion of a new entry).
    :return: List of tuples representing the possible divisions.
    """
    m = min_entries
    return [(entries[:(m-1+k)], entries[(m-1+k):]) for k in range(1, max_entries - 2*m + 3)]


def choose_split_index(distributions: List[EntryDistribution]) -> int:
    """
    Chooses the best split index based on minimum overlap (or minimum area in case of tie).
    :param distributions: List of possible distributions of entries along the best split axis.
    :return: Index of the best distribution among the list of possible distributions.
    """
    division_rects = [d.get_rects() for d in distributions]
    division_overlaps = [r1.get_intersection_area(r2) for r1, r2 in division_rects]
    min_overlap = min(division_overlaps)
    indices = [i for i, v in enumerate(division_overlaps) if math.isclose(v, min_overlap, rel_tol=EPSILON)]
    # If a single index is a clear winner, choose that index.
    if len(indices) == 1:
        return indices[0]
    else:
        # Resolve ties by choosing the distribution with minimum area
        min_area = None
        split_index = None
        for i in indices:
            r1, r2 = division_rects[i]
            area = r1.area() + r2.area()
            if min_area is None or area < min_area:
                min_area = area
                split_index = i
        return split_index


def rstar_split(tree: RTreeBase[T], node: RTreeNode[T]) -> RTreeNode[T]:
    """
    Split an overflowing node. The R*-Tree implementation first determines the optimum split axis (minimizing overall
    perimeter), then chooses the best split index along the chosen axis (based on minimum overlap).
    :param tree: RTreeBase[T]: R-tree instance.
    :param node: RTreeNode[T]: Overflowing node that needs to be split.
    :return: Newly-created split node whose entries are a subset of the original node's entries.
    """
    stat = get_rstar_stat(node.entries, tree.min_entries, tree.max_entries)
    axis = choose_split_axis(stat)
    distributions = stat.get_axis_unique_distributions(axis)
    i = choose_split_index(distributions)
    distribution = distributions[i]
    d1 = list(distribution.set1)
    d2 = list(distribution.set2)
    return tree.perform_node_split(node, d1, d2)
