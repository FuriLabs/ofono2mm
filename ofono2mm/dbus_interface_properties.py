from typing import Dict, List, Callable
from dbus_fast import Variant
from ofono2mm.logging import ofono2mm_print
import asyncio

class DBusInterfaceProperties:
    """A class that offers a dict-like interface to a DBus interface's properties.
    It also watches for property changes and updates the internal dict accordingly.
    Usage:
        'Present' in self.ofono_interface_props['org.ofono.SimManager'] -> returns True or False if the property is present
        self.ofono_interface_props['org.ofono.SimManager']['Present'] -> returns the value of the property
        self.ofono_interface_props['org.ofono.SimManager'].on('Present', self.on_present_changed) -> calls self.on_present_changed when the property changes
    """
    class DBusInterface:
        """What you get when you access a property of a DBusInterfaceProperties object.
        It's a dict that can be accessed and modified like a normal dict, but also has the on() thing.
        """
        def __init__(self, ofono_proxy, interface, verbose):
            self.ofono_proxy = ofono_proxy
            self.interface = interface
            self.verbose = verbose
            self.props: Dict[str, Variant] = {}
            self.watchers: Dict[str, List[Callable]] = {}
            self.initialized = False
            self._proxy = None
            self._init_lock = asyncio.Lock()
            self._pending_changes = None

        async def init(self, skip_props=False):
            async with self._init_lock:
                if self.initialized:
                    return
                if skip_props:
                    self.initialized = True
                    return

                # Keep the proxy we subscribe on so retries and removal can
                # disconnect the same handler instead of leaking subscriptions.
                self._proxy = self.ofono_proxy[self.interface]
                self._proxy.on_property_changed(self._on_property_changed)
                try:
                    for attempt in range(3):
                        self._pending_changes = {}
                        try:
                            props = await self._proxy.call_get_properties()
                            # Signals received while GetProperties was pending
                            # are newer than the returned snapshot.
                            props.update(self._pending_changes)
                            self.props = props
                            self.initialized = True
                            return
                        except Exception:
                            if attempt == 2:
                                raise
                            await asyncio.sleep(0.5)
                except Exception:
                    self.invalidate()
                    raise
                finally:
                    self._pending_changes = None

        def invalidate(self):
            if self._proxy is not None:
                self._proxy.off_property_changed(self._on_property_changed)
                self._proxy = None
            self.props.clear()
            self.initialized = False

        def __getitem__(self, prop):
            if prop in self.props:
                return self.props[prop]
            raise KeyError(f"Property {prop} not found in {self.interface}")

        def __setitem__(self, prop, value):
            if prop in self.props:
                running_loop = asyncio.get_running_loop()
                running_loop.create_task(self.ofono_proxy[self.interface].call_set_property(prop, value))
                self.props[prop] = value
            else:
                raise KeyError(f"Property {prop} not found in {self.interface}")

        def __contains__(self, prop):
            return prop in self.props

        async def _on_property_changed(self, prop, value):
            if self._pending_changes is not None:
                self._pending_changes[prop] = value
            if prop in self.props and self.props[prop].value == value.value:
                # Well that ain't much of a change innit
                return
            self.props[prop] = value

            # Watchers can be asynchronous, so we have to explicitly check for that and await them.
            # Otherwise, Python gets upset.
            if prop in self.watchers:
                for watcher in self.watchers[prop]:
                    if asyncio.iscoroutinefunction(watcher):
                        await watcher(prop, value)
                    else:
                        watcher(prop, value)

            if '*' in self.watchers:
                for watcher in self.watchers['*']:
                    if asyncio.iscoroutinefunction(watcher):
                        await watcher(prop, value)
                    else:
                        watcher(prop, value)

        def on(self, prop, callback):
            if prop not in self.watchers:
                self.watchers[prop] = []
            if callback not in self.watchers[prop]:
                self.watchers[prop].append(callback)

    def __init__(self, ofono_proxy, verbose):
        self.ofono_proxy = ofono_proxy
        self.verbose = verbose
        self.interfaces: Dict[str, DBusInterface] = {}

    def __getitem__(self, interface: str) -> Dict[str, any]:
        if interface in self.interfaces:
            return self.interfaces[interface]

        self.interfaces[interface] = self.DBusInterface(self.ofono_proxy, interface, self.verbose)
        return self.interfaces[interface]

    def __contains__(self, interface: str) -> bool:
        return interface in self.interfaces and self.interfaces[interface].initialized
