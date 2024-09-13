from typing import Dict, List, Callable
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

        async def init(self, skip_props=False):
            if skip_props:
                return
            retries_left = 3
            # Sometimes interfaces appear but their methods, properties, etc are not ready yet
            # So we'll cut it some slack
            while retries_left > 0:
                try:
                    self.props = await self.ofono_proxy[self.interface].call_get_properties()
                    # Watch for property changes to update the internal dict
                    self.ofono_proxy[self.interface].on_property_changed(self._on_property_changed)
                    return
                except Exception as e:
                    retries_left -= 1
                    if retries_left > 0:
                        await asyncio.sleep(0.5)
                    else:
                        ofono2mm_print(f"Interface {self.interface} doesn't have properties? {e}", self.verbose)

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

        def _on_property_changed(self, prop, value):
            if prop in self.props and self.props[prop].value == value.value:
                # Well that ain't much of a change innit
                return
            self.props[prop] = value
            if prop in self.watchers:
                for watcher in self.watchers[prop]:
                    watcher(prop, value)
            if '*' in self.watchers:
                for watcher in self.watchers['*']:
                    watcher(prop, value)

        def on(self, prop, callback):
            if prop not in self.watchers:
                self.watchers[prop] = []
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
        return interface in self.interfaces
