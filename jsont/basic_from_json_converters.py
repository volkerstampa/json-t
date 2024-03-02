from abc import ABC, abstractmethod
from inspect import isclass
from types import NoneType
from typing import (Any, Callable, Generic, Iterable, Literal, Mapping, Optional, Protocol,
                    Sequence, TypeVar, Union, cast, get_args, runtime_checkable)

from jsont.base_types import Json, JsonSimple

TargetType = TypeVar("TargetType")
ContainedTargetType = TypeVar("ContainedTargetType")


class FromJsonConverter(ABC, Generic[TargetType, ContainedTargetType]):
    """The base-class for converters that convert from objects representing JSON.

    Converters that convert from objects representing JSON to their specific python object have to
    implement the two abstract methods defined in this base-class.

    TargetType:
        The type this converter converts objects representing JSON to.

    ContainedTargetType:
        If ``TargetType`` is a container type (like ``Sequence`` for example)
        this is the type of the objects the container contains (e.g. the type of the elements
        of a ``Sequence``).
    """

    @abstractmethod
    def can_convert(self, target_type: type, origin_of_generic: Optional[type]) -> bool:
        """Return if this converts from an object representing JSON into the given ``target_type``.

        Args:
            target_type: the type this converter may or may not convert an object that represents
                JSON into.
            origin_of_generic: the unsubscripted version of ``target_type`` (i.e. without
                type-parameters). This origin is computed with :func:`typing.get_origin`.
        Returns:
            ``True`` if this converter can convert into ``target_type``, ``False`` otherwise.
        """

    @abstractmethod
    def convert(
            self,
            js: Json,
            target_type: type[TargetType],
            annotations: Mapping[str, type],
            from_json: Callable[[Json, type[ContainedTargetType]], ContainedTargetType]
    ) -> TargetType:
        """Convert the given object representing JSON to the given target type.

        Args:
            js: the JSON-representation to convert
            target_type: the type to convert to
            annotations: the annotations dict for ``target_type`` as returned by
                :func:`inspect.get_annotations`
            from_json: If this converter converts into container types like :class:`typing.Sequence`
                this function is used to convert the contained JSON-nodes into their respective
                target-types.
        Returns:
            the converted object of type ``target_type``
        Raises:
            ValueError: If the JSON-representation cannot be converted an instance of
                ``target_type``.
        """


class ToAny(FromJsonConverter[Any, None]):
    """Convert to the target type :class:`typing.Any`.

    This converter returns the object representing JSON unchanged.
    """

    def can_convert(self, target_type: type, origin_of_generic: Optional[type]) -> bool:
        return target_type is Any or target_type is object

    def convert(self,
                js: Json,
                target_type: type[Any],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, type[None]], None]) -> Any:
        return js


class ToUnion(FromJsonConverter[TargetType, TargetType]):
    """Convert to one of the type-parameters of the given ``typing.Union``.

    It tries to convert the object representing JSON to one of the type-parameters
    of the ``Union``-type in the order of their occurrence and returns the
    first successful conversion result. If none is successful it raises a
    :exc:`ValueError`.

    A ``target_type`` like ``Union[int, str]`` can be used to convert
    for example a ``5`` or a ``"Hello World!"``, but will fail to convert
    a ``list``.
    """

    def can_convert(self, target_type: type, origin_of_generic: Optional[type]) -> bool:
        # Union is a type-special-form and thus cannot be compared to a type
        return origin_of_generic is cast(type, Union)

    def convert(self,
                js: Json,
                target_type: type[TargetType],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, type[TargetType]], TargetType]) -> TargetType:
        union_types = get_args(target_type)
        # a str is also a Sequence of str so check str first to avoid that
        # it gets converted to a Sequence of str
        union_types_with_str_first = (([str] if str in union_types else [])
                                      + [ty for ty in union_types if ty is not str])
        args: Iterable[tuple[Json, type[Json]]] = ((js, ty) for ty in union_types_with_str_first)
        res_or_failures = _first_success(from_json, args)
        if res_or_failures \
                and isinstance(res_or_failures, list) \
                and all(isinstance(e, ValueError) for e in res_or_failures):
            raise ValueError(f"Cannot convert {js} to any of {union_types_with_str_first}: "
                             f"{list(zip(union_types_with_str_first, res_or_failures))}")
        # here we know that one conversion was successful. As we only convert into the
        # type-parameters of the Union the returned result must be of the Union-type
        return cast(TargetType, res_or_failures)


class ToLiteral(FromJsonConverter[TargetType, None]):
    """Convert to one of the listet literals.

    Returns the JSON-representation unchanged if it equals one of the literals, otherwise
    it raises a :exc:`ValueError`

    A ``target_type`` like ``Literal[5, 6]`` can be used to convert
    for example a ``5`` or a ``6``, but not a ``7``.
    """

    def can_convert(self, target_type: type, origin_of_generic: Optional[type]) -> bool:
        # Literal is a type-special-form and thus cannot be compared to a type
        return origin_of_generic is cast(type, Literal)

    def convert(self,
                js: Json,
                target_type: type[TargetType],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, type[None]], None]) -> TargetType:
        literals = get_args(target_type)
        if js in literals:
            # as js is one of the literals it must be of the Literal[literals]-type
            return cast(TargetType, js)
        raise ValueError(f"Cannot convert {js} to any of {literals}")


class ToNone(FromJsonConverter[None, None]):
    """Return the JSON-representation, if it is ``None``.

    If the given JSON-representation is not ``None`` it raises an :exc:`ValueError`.
    """

    def can_convert(self, target_type: type, origin_of_generic: Optional[type]) -> bool:
        return target_type is NoneType or target_type is None

    def convert(self,
                js: Json,
                target_type: type[Any],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, type[None]], None]) -> None:
        if js is None:
            return None
        raise ValueError(f"Cannot convert {js} to None")


class ToSimple(FromJsonConverter[TargetType, None]):
    """Return the JSON-representation, if it is one of the types ``int, float, str, bool``."""

    def can_convert(self, target_type: type, origin_of_generic: Optional[type]) -> bool:
        return isclass(target_type) and issubclass(target_type, get_args(JsonSimple))

    def convert(self,
                js: Json,
                target_type: type[TargetType],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, type[None]], None]) -> TargetType:
        if isinstance(js, target_type):
            return js
        raise ValueError(f"Cannot convert {js} to {target_type}")


class ToTuple(FromJsonConverter[tuple[Any, ...], Any]):
    """Convert an array to a :class:`tuple`.

    Convert the elements of the array in the corresponding target type given by the type-parameter
    of the :class:`tuple` in the same position as the element. Raises :exc:`ValueError` if
    the number of type-parameters do not match to the number of elements.

    The type-parameters may contain a single ``...`` which is replaced by as many ``Any`` such that
    the number of type-parameters equals the number of elements. So a target type of
    ``tuple[int, ..., str]`` is equivalent to a target type of ``tuple[int, Any, Any, Any, str]``
    if the JSON-representation to be converted is a :class:`typing.Sequence` of 5 elements.

    A target type like ``tuple[int, str]`` can convert for example the list ``[5, "Hello World!"]``
    into the tuple ``(5, "Hello World!")``, but not ``["Hello World!", 5]``
    """

    def can_convert(self, target_type: type, origin_of_generic: Optional[type]) -> bool:
        return isclass(origin_of_generic) and issubclass(origin_of_generic, tuple)

    def convert(self,
                js: Json,
                target_type: type[tuple[Any, ...]],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, type[Any]], Any]) -> tuple[Any, ...]:
        element_types: Sequence[Any] = get_args(target_type)
        if element_types.count(...) > 1:
            raise ValueError(f"Cannot convert {js} to {target_type} "
                             f"as {target_type} has more than one ... parameter")
        if isinstance(js, Sequence):
            element_types = _replace_ellipsis(element_types, len(js))
            if len(js) != len(element_types):
                raise ValueError(
                    f"Cannot convert {js} to {target_type} "
                    "as number of type parameter do not match")
            return tuple(from_json(e, ty) for e, ty in zip(js, element_types))
        raise ValueError(f"Cannot convert {js} to {target_type} as types are not convertible")


class ToList(FromJsonConverter[Sequence[TargetType], TargetType]):
    """Convert an array to a :class:`typing.Sequence`.

    Convert all elements of the array into the corresponding target type given by the type-parameter
    of the :class:`typing.Sequence`.

    A target type of ``Sequence[int]`` can convert a ``list`` of ``int``,
    but not a ``list`` of ``str``.
    """

    def can_convert(self, target_type: type, origin_of_generic: Optional[type]) -> bool:
        return isclass(origin_of_generic) and issubclass(cast(type, origin_of_generic), Sequence)

    def convert(self,
                js: Json,
                target_type: type[Sequence[TargetType]],
                annotations: Mapping[str, type],
                from_json: Callable[[Json, type[TargetType]], TargetType]) -> Sequence[TargetType]:
        element_types = get_args(target_type) or (Any,)
        assert len(element_types) == 1
        if isinstance(js, Sequence):
            return [from_json(e, element_types[0]) for e in js]
        raise ValueError(f"Cannot convert {js} to {target_type}")


class ToMapping(FromJsonConverter[Mapping[str, TargetType], TargetType]):
    """Convert the JSON-representation to a :class:`typing.Mapping`.

    Convert all entries of the given ``Mapping`` (respectively JSON-object) into entries of a
    ``Mapping`` with the given key and value target types.

    A target type of ``Mapping[str, int]`` can convert for example ``{ "key1": 1, "key2": 2 }``.
    """

    def can_convert(self, target_type: type, origin_of_generic: Optional[type]) -> bool:
        return isclass(origin_of_generic) and issubclass(cast(type, origin_of_generic), Mapping)

    def convert(
            self,
            js: Json,
            target_type: type[Mapping[str, TargetType]],
            annotations: Mapping[str, type],
            from_json: Callable[[Json, type[TargetType]], TargetType]
    ) -> Mapping[str, TargetType]:
        key_value_types = get_args(target_type) or (str, Any)
        key_type, value_type = key_value_types
        if key_type is not str:
            raise ValueError(f"Cannot convert {js} to mapping with key-type: {key_type}")
        if isinstance(js, Mapping):
            return {k: from_json(v, value_type) for k, v in js.items()}
        raise ValueError(f"Cannot convert {js} to {target_type}")


@runtime_checkable
class HasRequiredKeys(Protocol):  # pylint: disable=too-few-public-methods
    __required_keys__: frozenset[str]


class ToTypedMapping(FromJsonConverter[Mapping[str, TargetType], TargetType]):
    """Convert the JSON-representation to a :class:`typing.TypedDict`.

    Convert all entries of the given ``Mepping`` (respectively JSON-object) into entries of a
    ``TypedDict`` with the given key and value target types.

    Args:
        strict: indicates if the conversion of a ``Mapping`` should fail, if is contains more
            keys than the provided target type. Pass ``True`` to make it fail in this case.
            Defaults to ``False``.

    Example:
        >>> from typing import TypedDict
        >>>
        >>> # using the ToTypedMapping converter one can convert for example:
        >>> json_object = {"k1": 1.0, "k2": 2, "un": "known"}
        >>> # into the following:
        >>> class Map(TypedDict):
        ...     k1: float
        ...     k2: int
        >>> # In this example the result will meet:
        >>> # assert result == {"k1": 1.0, "k2": 2}

    """

    def __init__(self, strict: bool = False):
        self.strict = strict

    def can_convert(self, target_type: type, origin_of_generic: Optional[type]) -> bool:
        return isclass(target_type) and issubclass(target_type, Mapping)

    def convert(
            self,
            js: Json,
            target_type: type[Mapping[str, TargetType]],
            annotations: Mapping[str, type[TargetType]],
            from_json: Callable[[Json, type[TargetType]], TargetType]
    ) -> Mapping[str, TargetType]:
        def type_for_key(k: str) -> type[TargetType]:
            t = annotations.get(k)
            if t:
                return t
            raise ValueError(f"Cannot convert {js} to {target_type} as it contains unknown key {k}")

        if isinstance(js, Mapping) and isinstance(target_type, HasRequiredKeys):
            if target_type.__required_keys__.issubset(frozenset(js.keys())):
                items = js.items() if self.strict \
                    else [(k, v) for k, v in js.items() if k in annotations]
                return {k: from_json(v, type_for_key(k)) for k, v in items}
            raise ValueError(
                f"Cannot convert {js} to {target_type} "
                "as it does not contain all required keys "
                f"{target_type.__required_keys__}"
            )
        raise ValueError(f"Cannot convert {js} to {target_type}")


def _first_success(f: Callable[..., ContainedTargetType], i: Iterable[tuple[TargetType, ...]]) \
        -> Union[ContainedTargetType, Sequence[ValueError]]:
    failures: list[ValueError] = []
    for args in i:
        try:
            return f(*args)
        except ValueError as e:
            failures.append(e)
    return failures


def _replace_ellipsis(element_types: Sequence[Any], expected_len: int) -> Sequence[Any]:
    if ... in element_types:
        element_types = _fill_ellipsis(element_types, expected_len, object)
    return element_types


def _fill_ellipsis(types: Sequence[Any], expected_len: int, fill_type: type[TargetType]) \
        -> Sequence[type[TargetType]]:
    types = list(types)
    ellipsis_idx = types.index(...)
    types[ellipsis_idx:ellipsis_idx + 1] = [fill_type] * (expected_len - len(types) + 1)
    return types
