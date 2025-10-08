"""
Menu Injection Helper
=====================

This module provides a reusable helper for inserting custom operators into
Blender menus without re-implementing Blender's stock draw functions.  It is
designed to be copy/pasted between add-ons and to be friendly to automated
coding agents that need to refactor legacy overrides.

Quick Start
-----------
1. Copy this file next to your add-on's ``__init__.py``.
2. Import the helpers in your module::

       from .menu_injector import register_menu_item, unregister_menu_item

3. During registration call :func:`register_menu_item` and keep the returned
   handle so you can unregister cleanly::

       _MENU_HANDLE = None

       def register():
           global _MENU_HANDLE
           _MENU_HANDLE = register_menu_item(
               menu="VIEW3D_MT_object",
               operator="object.delete",
               label="Delete (Demo)",
               anchor_operator="object.join",
               before_anchor=False,
               is_enabled=lambda ctx: ctx.object is not None,
               icon='TRASH',
           )

       def unregister():
           global _MENU_HANDLE
           if _MENU_HANDLE is not None:
               unregister_menu_item(_MENU_HANDLE)
               _MENU_HANDLE = None

Parameter Reference
-------------------
``menu`` (str | :class:`bpy.types.Menu`):
    Target menu to augment.  Accepts the RNA name (e.g.
    ``"VIEW3D_MT_object"``) or the menu class itself.

``operator`` (str | :class:`bpy.types.Operator` subclass):
    Operator triggered by the new menu entry.  You may pass the id string or
    the operator class; the helper extracts ``bl_idname`` automatically.

``label`` (str):
    Text displayed in the menu.

``anchor_operator`` (str | None):
    RNA operator id used as positional anchor.  When ``None`` the new entry is
    appended to the end of the menu.

``before_anchor`` (bool):
    If ``True`` (default) the item is inserted before the anchor, otherwise it
    is inserted after the anchor.

``icon`` (str):
    Optional Blender icon identifier (default ``'NONE'``).

``is_enabled`` (Callable[[bpy.types.Context], bool] | None):
    Optional callback returning ``True`` when the menu item should be enabled.
    When omitted the entry is always enabled.

``operator_settings`` (dict | None):
    Optional mapping of property names to values that are applied to the
    operator button instance (useful for presets).

Implementation Notes
--------------------
* The helper temporarily patches :class:`bpy.types.UILayout.__getattribute__`
  during menu draw calls to detect where Blender inserts operators.
* A thread-local stack keeps the hook safe for nested layouts.
* The returned :class:`MenuInjectionHandle` is an opaque token; store it and
  pass it back to :func:`unregister_menu_item` during add-on shutdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Union
import threading

import bpy
from bpy.types import Menu, Operator

__all__ = [
    "MenuInjectionHandle",
    "MenuEntryHandle",
    "register_menu_item",
    "unregister_menu_item",
    "register_menu_entry",
    "unregister_menu_entry",
]

MenuRef = Union[str, type]
OperatorRef = Union[str, type]
EnableCallback = Optional[Callable[[bpy.types.Context], bool]]


@dataclass(slots=True)
class MenuInjectionHandle:
    """
    Opaque handle returned by :func:`register_menu_item`.

    Attributes
    ----------
    menu_cls:
        Target menu class (resolved from the ``menu`` argument).
    anchor_operator:
        RNA operator id used as positional reference (``None`` means append).
    before_anchor:
        ``True`` when the item should appear before the anchor.
    operator_id:
        RNA id of the operator triggered by the menu item.
    label:
        Display text shown in the UI.
    icon:
        Blender icon identifier string.
    is_enabled:
        Optional callback controlling the enabled state.
    operator_settings:
        Optional property overrides applied to the operator button.
    """

    menu_cls: type[Menu]
    anchor_operator: Optional[str]
    before_anchor: bool
    operator_id: str
    label: str
    icon: str
    is_enabled: EnableCallback
    operator_settings: Optional[Dict[str, Any]]
    _used_in_draw: bool = False


MenuEntryHandle = MenuInjectionHandle  # Backwards compatibility alias


class _MenuDrawManager:
    __slots__ = ("layout", "context", "handles")

    def __init__(self, layout, context, handles: Sequence[MenuInjectionHandle]):
        self.layout = layout
        self.context = context
        self.handles = handles
        for handle in self.handles:
            handle._used_in_draw = False

    def _dispatch(self, predicate: Callable[[MenuInjectionHandle], bool], operator_id: str):
        for handle in self.handles:
            if (
                handle.anchor_operator == operator_id
                and predicate(handle)
                and not handle._used_in_draw
            ):
                self._draw_handle(handle)

    def _draw_handle(self, handle: MenuInjectionHandle):
        layout = self.layout if handle.is_enabled is None else self.layout.row()
        if handle.is_enabled is not None:
            layout.enabled = bool(handle.is_enabled(self.context))
        button = layout.operator(handle.operator_id, text=handle.label, icon=handle.icon)
        if handle.operator_settings:
            for attr, value in handle.operator_settings.items():
                setattr(button, attr, value)
        handle._used_in_draw = True

    def before_operator(self, operator_id: str):
        self._dispatch(lambda handle: handle.before_anchor, operator_id)

    def after_operator(self, operator_id: str):
        self._dispatch(lambda handle: not handle.before_anchor, operator_id)

    def finalize(self):
        for handle in self.handles:
            if not handle._used_in_draw:
                self._draw_handle(handle)
            handle._used_in_draw = False


_MENU_STATE: Dict[type[Menu], Dict[str, Any]] = {}
_HOOK_DEPTH = 0
_THREAD_LOCAL = threading.local()
_ORIGINAL_GETATTRIBUTE = None


def _current_manager() -> Optional[_MenuDrawManager]:
    stack = getattr(_THREAD_LOCAL, "manager_stack", None)
    if stack:
        return stack[-1]
    return None


def _layout_getattribute_hook(self, item):
    original_getattribute = _ORIGINAL_GETATTRIBUTE or object.__getattribute__
    attr = original_getattribute(self, item)
    if item != "operator":
        return attr
    manager = _current_manager()
    if manager is None:
        return attr

    def _operator_proxy(operator_id, *args, **kwargs):
        manager.before_operator(operator_id)
        result = attr(operator_id, *args, **kwargs)
        manager.after_operator(operator_id)
        return result

    return _operator_proxy


def _push_manager(manager: _MenuDrawManager):
    global _HOOK_DEPTH, _ORIGINAL_GETATTRIBUTE
    stack: List[_MenuDrawManager] = getattr(_THREAD_LOCAL, "manager_stack", [])
    stack.append(manager)
    _THREAD_LOCAL.manager_stack = stack
    _HOOK_DEPTH += 1
    if _HOOK_DEPTH == 1:
        if _ORIGINAL_GETATTRIBUTE is None:
            _ORIGINAL_GETATTRIBUTE = bpy.types.UILayout.__getattribute__
        bpy.types.UILayout.__getattribute__ = _layout_getattribute_hook


def _pop_manager():
    global _HOOK_DEPTH
    stack: List[_MenuDrawManager] = getattr(_THREAD_LOCAL, "manager_stack", [])
    if not stack:
        return
    stack.pop()
    if stack:
        _THREAD_LOCAL.manager_stack = stack
    elif hasattr(_THREAD_LOCAL, "manager_stack"):
        delattr(_THREAD_LOCAL, "manager_stack")
    _HOOK_DEPTH -= 1
    if _HOOK_DEPTH == 0 and _ORIGINAL_GETATTRIBUTE is not None:
        bpy.types.UILayout.__getattribute__ = _ORIGINAL_GETATTRIBUTE


def _resolve_menu(menu: MenuRef) -> type[Menu]:
    if isinstance(menu, str):
        return getattr(bpy.types, menu)
    return menu


def _resolve_operator_id(operator: OperatorRef) -> str:
    if isinstance(operator, str):
        return operator
    if isinstance(operator, type) and issubclass(operator, Operator):
        return operator.bl_idname
    raise TypeError("operator must be an operator id string or Operator subclass")


def register_menu_item(
    *,
    menu: MenuRef,
    operator: OperatorRef,
    label: str,
    anchor_operator: Optional[str] = None,
    before_anchor: bool = True,
    icon: str = "NONE",
    is_enabled: EnableCallback = None,
    operator_settings: Optional[Dict[str, Any]] = None,
) -> MenuInjectionHandle:
    """
    Register a new menu entry and return a handle that can later be passed to
    :func:`unregister_menu_item`.
    """

    menu_cls = _resolve_menu(menu)
    operator_id = _resolve_operator_id(operator)
    descriptor = _MENU_STATE.get(menu_cls)

    if descriptor is None:
        descriptor = {
            "original_draw": menu_cls.draw,
            "handles": [],
        }
        _MENU_STATE[menu_cls] = descriptor

        def _wrapped_draw(self, context):
            manager = _MenuDrawManager(self.layout, context, descriptor["handles"])
            _push_manager(manager)
            try:
                descriptor["original_draw"](self, context)
            finally:
                try:
                    manager.finalize()
                finally:
                    _pop_manager()

        menu_cls.draw = _wrapped_draw

    handle = MenuInjectionHandle(
        menu_cls=menu_cls,
        anchor_operator=anchor_operator,
        before_anchor=bool(before_anchor),
        operator_id=operator_id,
        label=label,
        icon=icon,
        is_enabled=is_enabled,
        operator_settings=dict(operator_settings) if operator_settings else None,
    )
    descriptor["handles"].append(handle)
    return handle


def unregister_menu_item(handle: Optional[MenuInjectionHandle]):
    """
    Remove a previously registered menu entry.  Safe to call multiple times.
    """

    if handle is None:
        return

    descriptor = _MENU_STATE.get(handle.menu_cls)
    if descriptor is None:
        return

    handles: List[MenuInjectionHandle] = descriptor["handles"]
    if handle in handles:
        handles.remove(handle)

    if handles:
        return

    handle.menu_cls.draw = descriptor["original_draw"]
    del _MENU_STATE[handle.menu_cls]


def register_menu_entry(
    *,
    menu: MenuRef,
    operator: OperatorRef,
    label: str,
    relative_to: Optional[str] = None,
    position: str = "after",
    icon: str = "NONE",
    is_enabled: EnableCallback = None,
    operator_kwargs: Optional[Dict[str, Any]] = None,
) -> MenuEntryHandle:
    """
    Backwards compatible wrapper for older call sites.
    """

    pos_norm = (position or "after").strip().lower()
    if pos_norm not in {"before", "after"}:
        raise ValueError("position must be 'before' or 'after'")
    before_anchor = pos_norm != "after"
    return register_menu_item(
        menu=menu,
        operator=operator,
        label=label,
        anchor_operator=relative_to,
        before_anchor=before_anchor,
        icon=icon,
        is_enabled=is_enabled,
        operator_settings=operator_kwargs,
    )


def unregister_menu_entry(handle: Optional[MenuEntryHandle]) -> None:
    """
    Backwards compatible wrapper for older call sites.
    """

    unregister_menu_item(handle)
