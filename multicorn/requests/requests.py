# -*- coding: utf-8 -*-
# Copyright © 2008-2011 Kozea
# This file is part of Multicorn, licensed under a 3-clause BSD license.


import sys
import functools

# Marker to distinguish "Nothing was given" and "`None` was explicitly given".
ARGUMENT_NOT_GIVEN = object()


def literal(obj):
    """
    Wrap any Python object into a request that represents that object.
    """
    return LiteralRequest(obj)


def as_request(obj):
    """
    Return a Request object for `obj`.
    """
    if isinstance(obj, Request):
        return obj
    elif isinstance(obj, list):
        return ListRequest(obj)
    elif isinstance(obj, tuple):
        return TupleRequest(obj)
    elif isinstance(obj, dict):
        return DictRequest(obj)
    else:
        return LiteralRequest(obj)


def as_chain(request):
    """Return a  request as a chain of successive operations"""
    chain = [request]
    request = WithRealAttributes(request)
    if issubclass(request.obj_type(), OperationRequest) and \
            not issubclass(request.obj_type(), BinaryOperationRequest):
        chain = as_chain(request.subject) + chain
    return chain



class WithRealAttributes(object):
    """
    Wrap a Request object to allow access to its attributes without going
    through `Request.__getattribute__` and `Request.__setattr__`.
    """
    __slots__ = ('_wrapped_obj',)

    def __init__(self, obj):
        object.__setattr__(self, '_wrapped_obj', obj)

    def __getattr__(self, name):
        return object.__getattribute__(self._wrapped_obj, name)

    def __setattr__(self, name, value):
        object.__setattr__(self._wrapped_obj, name, value)

    def obj_type(self):
        return type(self._wrapped_obj)


def self_with_attrs(method):
    """
    Decorate a method so that the first argument `self` is wrapped with
    WithRealAttributes.
    """
    @functools.wraps(method)
    def decorated_method(self, *args, **kwargs):
        return method(WithRealAttributes(self), *args, **kwargs)
    return decorated_method


class Request(object):
    """
    Abstract base class for all request objects.

    This class defines special methods like `__add__` so that python operators
    can be used on requests, as in `req = req1 + req2`.

    In particular, this class defines `__getattribute__` so that attribute
    lookup as in `some_request.firstname` also returns a request, except for
    special methods: `some_request.__add__` will return the method. For
    consistency, assigning to request attributes is forbidden:
    `some_request.firstname = 'Alfred'` raises an exception.

    To access the actual attributes of Request objects, one needs to use
    `object.__getattribute__` and `object.__setattr__`.
    """


    context_switching_args = ()

    # TODO: test `del some_request.fistname`. It should raise.
    def __getattribute__(self, name):
        if name.startswith('__') and name.endswith('__'):
            # Special methods such as __add__.
            # According to the following link CPython may not go through here
            # to get them, but there seems to be no guarantee that it does not.
            # http://docs.python.org/reference/datamodel.html#new-style-special-lookup
            return object.__getattribute__(self, name)
        else:
            # No as_request() on the name
            return AttributeRequest(self, name)

    def __setattr__(self, name, value):
        raise AttributeError('Can not assign to request attributes.')


    def __getitem__(self, key):
        # XXX No as_request() on key ?
        if isinstance(key, slice):
            return SliceRequest(self, key)
        elif isinstance(key, int):
            return IndexRequest(self, key)
        raise TypeError('Request objects only support indexing and slicing, '
                        'not dict-like lookup.')

    def __iter__(self):
        raise TypeError('Request are not iterable. Did you mean to execute it?')

    def __invert__(self):
        # Simplify logic when possible
        if isinstance(self, LiteralRequest):
            return LiteralRequest(not WithRealAttributes(self).value)
        else:
            return NotRequest(self)

    def __and__(self, other):
        other = as_request(other)
        # Simplify logic when possible
        for a, b in ((self, other), (other, self)):
            if isinstance(a, LiteralRequest):
                if WithRealAttributes(a).value:
                    # True is the neutral element of and
                    return b
                else:
                    # False is the absorbing element
                    return LiteralRequest(False)
        return AndRequest(self, other)

    def __or__(self, other):
        other = as_request(other)
        # Simplify logic when possible
        for a, b in ((self, other), (other, self)):
            if isinstance(a, LiteralRequest):
                if WithRealAttributes(a).value:
                    # True is the absorbing element of or
                    return LiteralRequest(True)
                else:
                    # False is the neutral element
                    return b
        return OrRequest(self, other)

    # `&` and `|` are commutative
    __rand__ = __and__
    __ror__ = __or__

    def __eq__(self, other): return EqRequest(self, as_request(other))
    def __ne__(self, other): return NeRequest(self, as_request(other))
    def __lt__(self, other): return LtRequest(self, as_request(other))
    def __gt__(self, other): return GtRequest(self, as_request(other))
    def __le__(self, other): return LeRequest(self, as_request(other))
    def __ge__(self, other): return GeRequest(self, as_request(other))

    # Both __div__ and __truediv__ return a DivRequest, so that the meaning
    # of `some_req / other_req` does not depend on whether the module using
    # it has `from __future__ import division`
    def __add__(self, other): return AddRequest(self, as_request(other))
    def __sub__(self, other): return SubRequest(self, as_request(other))
    def __mul__(self, other): return MulRequest(self, as_request(other))
    def __div__(self, other): return DivRequest(self, as_request(other))
    def __pow__(self, other): return PowRequest(self, as_request(other))
    def __truediv__(self, other): return DivRequest(self, as_request(other))

    # Reflected methods: swap the arguments.
    def __radd__(self, other): return AddRequest(as_request(other), self)
    def __rsub__(self, other): return SubRequest(as_request(other), self)
    def __rmul__(self, other): return MulRequest(as_request(other), self)
    def __rpow__(self, other): return PowRequest(as_request(other), self)
    def __rdiv__(self, other): return DivRequest(as_request(other), self)
    def __rtruediv__(self, other): return DivRequest(as_request(other), self)

    def __neg__(self):
        return NegRequest(self)

    # __contains__ can be overriden, but it is useless here as its result is
    # converted to a bool: `some_req in other_req` can not be a Request.

    @self_with_attrs
    def __repr__(self):
        name = self.obj_type().__name__
        assert name.endswith('Request')
        name = name[:-len('Request')]
        return '%s[%s]' % (name, ', '.join(
            repr(getattr(self, attr_name)) for attr_name in self.arg_spec))

#    @self_with_attrs
#    def __hash__(self):
#        return hash(('this is a request hash',) + tuple(
#            getattr(self, attr_name) for attr_name in self.arg_spec))

    # Just like attributes, these methods can be accessed with eg.
    # `object.__getattribute__(some_req).map`, but AttributeRequest objects
    # are also callable so that `some_req.map(...)` Just Works™.
    def one(self, default=ARGUMENT_NOT_GIVEN):
        if default is ARGUMENT_NOT_GIVEN:
            default = None
        else:
            default = as_request(default)
        return OneRequest(self, default)

    def filter(self, predicate=ARGUMENT_NOT_GIVEN, **kwargs):
        if predicate is ARGUMENT_NOT_GIVEN:
            predicate = LiteralRequest(True)
        else:
            predicate = as_request(predicate)

        for name, value in kwargs.iteritems():
            predicate &= (getattr(ContextRequest(), name) == value)

        if isinstance(predicate, LiteralRequest):
            if object.__getattribute__(predicate, 'value'):
                # Skip the filter operation if the predicate is always true.
                return self
            # TODO: does the following this help? does it hurt?
#            else:
#                return LiteralRequest([])
        if isinstance(self, FilterRequest):
            this = WithRealAttributes(self)
            return FilterRequest(this.subject, this.predicate & predicate)

        return FilterRequest(self, predicate)

    def map(self, new_value):
        return MapRequest(self, as_request(new_value))

    def sort(self, *sort_keys):
        if not sort_keys:
            # Default to comparing the element themselves, ie req.sort()
            # is the same as req.sort(CONTEXT)
            sort_keys = (ContextRequest(),)

        # If a sort_key is a negation (NegRequest), unwrap it and mark it as
        # "reverse", so that we can sort in the other direction for sort keys
        # that do not have a negative value (ie. non-numbers)
        decorated_sort_keys = []
        for sort_key in sort_keys:
            sort_key = as_request(sort_key)
            wrapped_sort_key = WithRealAttributes(sort_key)
            reverse = (getattr(wrapped_sort_key, 'operator_name', '')
                       == 'neg')
            if reverse:
                sort_key = wrapped_sort_key.subject

            decorated_sort_keys.append((sort_key, reverse))
        return SortRequest(self, decorated_sort_keys)

    def groupby(self, key, **aggregates):
        if not aggregates:
            aggregates = {'elements': ContextRequest()}
        return GroupbyRequest(self, as_request(key), as_request(aggregates))

    def sum(self, subject=None):
        if subject is not None:
            return self.map(subject).sum()
        return SumRequest(self)

    def str(self):
        return StrRequest(self)

    def lower(self):
        return LowerRequest(self)

    def upper(self):
        return UpperRequest(self)

    def matches(self, other):
        return RegexRequest(self, other)

    def min(self, subject=None):
        if subject is not None:
            return self.map(subject).min()
        return MinRequest(self)

    def max(self, subject=None):
        if subject is not None:
            return self.map(subject).max()
        return MaxRequest(self)

    def len(self):
        return LenRequest(self)

    def distinct(self):
        return DistinctRequest(self)

    def execute(self, contexts=()):
        ap = WithRealAttributes(as_chain(self)[0])
        if hasattr(ap, 'storage'):
            assert not contexts
            return ap.storage.execute(self)
        else:
            from ..python_executor import execute
            return execute(self, contexts)

    @self_with_attrs
    def _visit(self, func, scope_depth=0):
        func(self._wrapped_obj, scope_depth)
        for arg_name in self.arg_spec:
            arg = getattr(self, arg_name)
            if isinstance(arg, Request):
                object.__getattribute__(arg, '_visit')(func, scope_depth + 1
                        if arg_name in self.context_switching_args
                        else scope_depth)

    @self_with_attrs
    def _copy_replace(self, replacements):
        newargs = []
        for arg_name in self.arg_spec:
            arg = getattr(self, arg_name)
            wrapper = WithRealAttributes(arg)
            found = False
            for key, replacement in replacements.iteritems():
                if arg is key:
                    newargs.append(replacement)
                    found = True
                    break
            if hasattr(wrapper, '_copy_replace'):
                arg = (wrapper._copy_replace(replacements))
            if not found:
                newargs.append(arg)
        return self.obj_type()(*newargs)


def method_repr(method_name):
    @self_with_attrs
    def __repr__(self):
        assert self.arg_spec[0] == 'subject'
        return '%r.%s(%s)' % (self.subject, method_name, ', '.join(
            repr(getattr(self, attr_name)) for attr_name in self.arg_spec[1:]))
    return __repr__


def unary_repr(operator):
    @self_with_attrs
    def __repr__(self):
        assert self.arg_spec == ('subject',)
        return '%s%r' % (operator, self.subject)
    return __repr__


def binary_repr(operator):
    @self_with_attrs
    def __repr__(self):
        assert self.arg_spec == ('subject', 'other')
        return '(%r %s %r)' % (self.subject, operator, self.other)
    return __repr__


class StoredItemsRequest(Request):
    """
    Represents the sequence of all items stored in a Storage
    """
    arg_spec = ('storage',)

    @self_with_attrs
    def __init__(self, storage):
        self.storage = storage

class LiteralRequest(Request):
    arg_spec = ('value',)

    @self_with_attrs
    def __init__(self, value):
        self.value = value

    @self_with_attrs
    def __repr__(self):
        return 'literal(%r)' % (self.value,)
        # This gives shorter outputs, but is confusing when printed by itself.
        #return repr(self.value)


class ListRequest(Request):
    arg_spec = ('value',)

    @self_with_attrs
    def __init__(self, obj):
        self.value = [as_request(element) for element in obj]


class TupleRequest(Request):
    arg_spec = ('value',)

    @self_with_attrs
    def __init__(self, obj):
        self.value = tuple(as_request(element) for element in obj)


class DictRequest(Request):
    arg_spec = ('value',)

    @self_with_attrs
    def __init__(self, obj):
        self.value = dict(
            # TODO: what about fancy keys? (non-unicode or even Request)
            (key, as_request(value))
            for key, value in obj.iteritems())

    @self_with_attrs
    def _visit(self, func, scope_depth=0):
        super(DictRequest, self._wrapped_obj)._visit(func, scope_depth)
        for value in self.value.values():
            if isinstance(value, Request):
                object.__getattribute__(value, '_visit')(func, scope_depth + 1)

class ContextRequest(Request):
    arg_spec = ('scope_depth',)

    @self_with_attrs
    def __init__(self, scope_depth=0):
        scope_depth = int(scope_depth)
        if scope_depth > 0:
            # TODO better message
            raise ValueError('Depth must be negative or zero.')
        self.scope_depth = scope_depth

    @self_with_attrs
    def __call__(self, more_depth):
        more_depth = int(more_depth)
        if more_depth > 0:
            # TODO better message
            raise ValueError('Depth must be negative or zero.')
        return ContextRequest(self.scope_depth + more_depth)

    @self_with_attrs
    def __repr__(self):
        if self.scope_depth == 0:
            return 'c'
        else:
            return 'c(%i)' % self.scope_depth


class OperationRequest(Request):
    """
    Abstract base class for requests that are based on at least one other
    request. That "main" sub-request is in the `subject` attribute.
    """
    # For subclasses: the name of the function in the `operator` module that
    # implement this operation, or None.
    # Eg. AddRequest.operator_name is 'add' so AddRequest(r1, r2) represents
    # `operator.__add__(v1, v2)` which is the same as `v1 + v2`, where r1 and
    # r2 respectively represent v1 and v2.
    operator_name = None


class UnaryOperationRequest(OperationRequest):
    """
    Abstract base class for request objects constructed with only one argument,
    another request object.

    Eg.  ~some_req is NotRequest(some_req)
    """

    arg_spec = ('subject',)

    @self_with_attrs
    def __init__(self, subject):
        self.subject = subject


class StrRequest(UnaryOperationRequest):
    """
    Convert a number to a string (unicode in python 2.x).
    """
    __repr__ = method_repr('str')


class LowerRequest(UnaryOperationRequest):
    """
    Return the lowercased version of the subject
    """
    __repr__ = method_repr('lower')


class UpperRequest(UnaryOperationRequest):
    """
    Return the uppercased version of the subject
    """
    __repr__ = method_repr('upper')


class NotRequest(UnaryOperationRequest):
    """
    Logical negation:  ~some_req is NotRequest(some_req)
    """
    # Returned by Request.__invert__, but we really want it to be `not`, not
    # `invert`. There is no __not__ special method that we can override.
    operator_name = 'not'
    __repr__ = unary_repr('~')


class NegRequest(UnaryOperationRequest):
    """
    Arithmetic negation:  -some_req is NegRequest(some_req)

    Although the bitwise inversion operator is used to construct it, this
    represents a boolean (logical) negation.
    """
    operator_name = 'neg'
    __repr__ = unary_repr('-')


class BinaryOperationRequest(OperationRequest):
    """
    Abstract base class for request objects constructed with two arguments,
    both request objects.

    Eg.  some_req + other_req is AddRequest(some_req, other_req)
    """

    arg_spec = ('subject', 'other')

    @self_with_attrs
    def __init__(self, subject, other):
        self.subject = subject
        self.other = other


class RegexRequest(BinaryOperationRequest):
    arg_spec = ('subject', 'other')
    __repr__ = method_repr('matches')


class EqRequest(BinaryOperationRequest):
    """
    some_req == other_req is EqRequest(some_req, other_req)
    """
    operator_name = 'eq'
    __repr__ = binary_repr('==')


class NeRequest(BinaryOperationRequest):
    """
    some_req != other_req is NeRequest(some_req, other_req)
    """
    operator_name = 'ne'
    __repr__ = binary_repr('!=')


class LtRequest(BinaryOperationRequest):
    """
    some_req < other_req is LtRequest(some_req, other_req)
    """
    operator_name = 'lt'
    __repr__ = binary_repr('<')


class GtRequest(BinaryOperationRequest):
    """
    some_req > other_req is GtRequest(some_req, other_req)
    """
    operator_name = 'gt'
    __repr__ = binary_repr('>')


class GeRequest(BinaryOperationRequest):
    """
    some_req >= other_req is GeRequest(some_req, other_req)
    """
    operator_name = 'ge'
    __repr__ = binary_repr('>=')


class LeRequest(BinaryOperationRequest):
    """
    some_req <= other_req is LeRequest(some_req, other_req)
    """
    operator_name = 'le'
    __repr__ = binary_repr('<=')


class AddRequest(BinaryOperationRequest):
    """
    some_req + other_req is AddRequest(some_req, other_req)
    """
    operator_name = 'add'
    __repr__ = binary_repr('+')


class SubRequest(BinaryOperationRequest):
    """
    some_req - other_req is SubRequest(some_req, other_req)
    """
    operator_name = 'sub'
    __repr__ = binary_repr('-')


class MulRequest(BinaryOperationRequest):
    """
    some_req * other_req is MulRequest(some_req, other_req)
    """
    operator_name = 'mul'
    __repr__ = binary_repr('*')


class DivRequest(BinaryOperationRequest):
    """
    some_req / other_req is DivRequest(some_req, other_req)

    Represents the true division, whether or not
    `from __future__ import divison` is present.
    """
    operator_name = 'truediv'
    __repr__ = binary_repr('/')


class PowRequest(BinaryOperationRequest):
    """
    some_req ** other_req is PowRequest(some_req, other_req)
    """
    operator_name = 'pow'
    __repr__ = binary_repr('**')


class AndRequest(BinaryOperationRequest):
    """
    some_req & other_req is AndRequest(some_req, other_req)

    Although the bitwise AND operator is used to construct it, this
    represents a boolean (logical) AND.
    """
    operator_name = 'and'
    __repr__ = binary_repr('&')


class OrRequest(BinaryOperationRequest):
    """
    some_req | other_req is OrRequest(some_req, other_req)

    Although the bitwise OR operator is used to construct it, this
    represents a boolean (logical) OR.
    """
    operator_name = 'or'
    __repr__ = binary_repr('|')


class SliceRequest(OperationRequest):
    """
    some_req[4:-1] is SliceRequest(some_req, slice(4, -1, None))
    other_req[::2] is SliceRequest(other_req, slice(None, None, 2))
    """

    arg_spec = ('subject', 'slice')

    @self_with_attrs
    def __init__(self, subject, slice_):
        self.subject = subject
        self.slice = slice_

    @self_with_attrs
    def __repr__(self):
        slice_args = []
        if self.slice.start:
            slice_args.append(str(self.slice.start))
        else:
            slice_args.append('')
        if self.slice.stop is not None:
            slice_args.append(str(self.slice.stop))
        else:
            slice_args.append('')
        if self.slice.step is not None:
            slice_args.append(str(self.slice.step))
        return '%r[%s]' % (self.subject, ':'.join(slice_args))


class IndexRequest(OperationRequest):
    """
    some_req[4] is IndexRequest(some_req, 4)
    other_req[-1] is IndexRequest(other_req, -1)
    """

    arg_spec = ('subject', 'index')

    @self_with_attrs
    def __init__(self, subject, index):
        self.subject = subject
        self.index = index

    @self_with_attrs
    def __repr__(self):
        return '%r[%i]' % (self.subject, self.index)


class AttributeRequest(OperationRequest):
    """
    some_req.firstname is AttributeRequest(req, 'firstname')

    Also has magic to implement methods on requests such as `some_req.one()`.
    """

    arg_spec = ('subject', 'attr_name')

    @self_with_attrs
    def __init__(self, subject, attr_name):
        self.subject = subject
        self.attr_name = attr_name

    @self_with_attrs
    def __call__(self, *args, **kwargs):
        """
        Implement methods on requests:
        eg. `some_req.map` is `GetattrRequest(some_req, 'map')`, but
        `some_req.map(...)` is `Request.map(some_req, ...)`.
        """
        method = getattr(WithRealAttributes(self.subject), self.attr_name, None)
        if method is None:
            raise TypeError('Request objects do not have a %s method.'
                            % self.attr_name)
        return method(*args, **kwargs)

    @self_with_attrs
    def __repr__(self):
        return '%r.%s' % (self.subject, self.attr_name)




class OneRequest(OperationRequest):
    arg_spec = ('subject', 'default')

    @self_with_attrs
    def __init__(self, subject, default):
        self.subject = subject
        self.default = default

    __repr__ = method_repr('one')


class FilterRequest(OperationRequest):
    arg_spec = ('subject', 'predicate')
    context_switching_args = ('predicate',)

    @self_with_attrs
    def __init__(self, subject, predicate):
        self.subject = subject
        self.predicate = predicate

    __repr__ = method_repr('filter')


class MapRequest(OperationRequest):
    arg_spec = ('subject', 'new_value')
    context_switching_args = ('new_value',)

    @self_with_attrs
    def __init__(self, subject, new_value):
        self.subject = subject
        self.new_value = new_value

    __repr__ = method_repr('map')


class SortRequest(OperationRequest):
    arg_spec = ('subject', 'sort_keys')
    context_switching_args = ('sort_keys',)

    @self_with_attrs
    def __init__(self, subject, sort_keys):
        self.subject = subject
        self.sort_keys = tuple(sort_keys)

    __repr__ = method_repr('sort')


class GroupbyRequest(OperationRequest):
    arg_spec = ('subject', 'key', 'aggregates')
    context_switching_args = ('key',)

    @self_with_attrs
    def __init__(self, subject, key, aggregates):
        self.subject = subject
        self.key = key
        self.aggregates = aggregates

    __repr__ = method_repr('groupby')


class SumRequest(UnaryOperationRequest):
    __repr__ = method_repr('sum')


class MinRequest(UnaryOperationRequest):
    __repr__ = method_repr('min')


class MaxRequest(UnaryOperationRequest):
    __repr__ = method_repr('max')


class LenRequest(UnaryOperationRequest):
    __repr__ = method_repr('len')


class DistinctRequest(UnaryOperationRequest):
    __repr__ = method_repr('distinct')
