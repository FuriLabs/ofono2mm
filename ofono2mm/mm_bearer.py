import asyncio

from copy import deepcopy
from pathlib import Path
from time import monotonic

from dbus_fast.service import ServiceInterface, method, dbus_property
from dbus_fast.constants import PropertyAccess
from dbus_fast import Variant

from ofono2mm.utils import async_retryable, save_setting, read_setting, netmask_to_prefix
from ofono2mm.logging import ofono2mm_print
from ofono2mm.types import ModemState

# oFono only replies to Active=True once the data call has actually been set up or has
# failed. On a modem where setup routinely takes longer than the previous 5s limit, a
# short timeout turns a still-pending activation into an apparent success.
ACTIVATE_TIMEOUT_SECONDS = 30.0

# Interface is filled in from oFono's Settings PropertyChanged signal, which can land
# after the Active=True method reply returns.
INTERFACE_WAIT_SECONDS = 5.0
INTERFACE_POLL_SECONDS = 0.1

class MMBearerInterface(ServiceInterface):
    def __init__(self, ofono_client, modem_name, ofono_interfaces, mm_modem, verbose=False):
        super().__init__('org.freedesktop.ModemManager1.Bearer')
        self.modem_name = modem_name
        ofono2mm_print("Initializing Bearer interface", verbose)
        self.ofono_client = ofono_client
        self.ofono_proxy = self.ofono_client["ofono_modem"][modem_name]
        self.ofono_interfaces = ofono_interfaces
        self.mm_modem = mm_modem
        self.verbose = verbose
        self.disconnecting = False
        self.ofono_ctx = None
        self._context_interface = None
        self._context_handler = None
        self.active_connect = 0
        self.own_object_path = None
        self.props = {
            "Interface": Variant('s', ''),
            "Connected": Variant('b', False),
            "Suspended": Variant('b', False),
            "Multiplexed": Variant('b', True),
            "Ip4Config": Variant('a{sv}', {
                "method": Variant('u', 3) # on runtime dhcp MM_BEARER_IP_METHOD_DHCP
            }),
            "Ip6Config": Variant('a{sv}', {
                "method": Variant('u', 3) # on runtime dhcp MM_BEARER_IP_METHOD_DHCP
            }),
            "ReloadStatsSupported": Variant('b', False),
            "IpTimeout": Variant('u', 0),
            "BearerType": Variant('u', 1),
            "Properties": Variant('a{sv}', {
                "apn": Variant('s', ''),
                "ip-type": Variant('u', 4), # hardcoded value ipv4/v6 MM_BEARER_IP_FAMILY_IPV4V6
                "apn-type": Variant('u', 2), # hardcoded value default internet MM_BEARER_APN_TYPE_DEFAULT
                "allowed-auth": Variant('u', 0), # on runtime unknown MM_BEARER_ALLOWED_AUTH_UNKNOWN
                "user": Variant('s', ''),
                "password": Variant('s', ''),
                "access-type-preference": Variant('u', 0), # on runtime none MM_BEARER_ACCESS_TYPE_PREFERENCE_NONE
                "roaming-allowance": Variant('u', 0), # on runtime none MM_BEARER_ROAMING_ALLOWANCE_NONE
                "profile-id": Variant('i', -1),
                "profile-name": Variant('s', ''),
                "profile-enabled": Variant('b', True),
                "profile-source": Variant('u', 0), # hardcoded value unknown MM_BEARER_PROFILE_SOURCE_UNKNOWN
            })
        }

    @dbus_property(access=PropertyAccess.READ)
    def Interface(self) -> 's':
        return self.props['Interface'].value

    @dbus_property(access=PropertyAccess.READ)
    def Connected(self) -> 'b':
        return self.props['Connected'].value

    @dbus_property(access=PropertyAccess.READ)
    def Suspended(self) -> 'b':
        return self.props['Suspended'].value

    @dbus_property(access=PropertyAccess.READ)
    def Multiplexed(self) -> 'b':
        return self.props['Multiplexed'].value

    @dbus_property(access=PropertyAccess.READ)
    def Ip4Config(self) -> 'a{sv}':
        return self.props['Ip4Config'].value

    @dbus_property(access=PropertyAccess.READ)
    def Ip6Config(self) -> 'a{sv}':
        return self.props['Ip6Config'].value

    @dbus_property(access=PropertyAccess.READ)
    def ReloadStatsSupported(self) -> 'b':
        return self.props['ReloadStatsSupported'].value

    @dbus_property(access=PropertyAccess.READ)
    def IpTimeout(self) -> 'u':
        return self.props['IpTimeout'].value

    @dbus_property(access=PropertyAccess.READ)
    def BearerType(self) -> 'u':
        return self.props['BearerType'].value

    @dbus_property(access=PropertyAccess.READ)
    def Properties(self) -> 'a{sv}':
        return self.props['Properties'].value

    async def set_props(self):
        ofono2mm_print("Setting properties", self.verbose)

        old_props = deepcopy(self.props)

        if 'org.ofono.ConnectionManager' in self.ofono_interfaces:
            # GetContexts can take a few seconds to come up. If we fail with a DBusError, we'll just wait a bit and try again.
            retries_left = 5
            while retries_left > 0:
                try:
                    ofono2mm_print(f"Call get contexts (attempts left: {retries_left})", self.verbose)
                    contexts = await self.ofono_proxy['org.ofono.ConnectionManager'].call_get_contexts()
                    break
                except Exception as e:
                    retries_left -= 1
                    if retries_left == 0:
                        ofono2mm_print(f"Failed to get contexts: {e}", self.verbose)
                        return
                    await asyncio.sleep(0.2)

            chosen_apn = ''
            chosen_auth_method = ''
            chosen_username = ''
            chosen_password = ''
            for ctx in contexts:
                name = ctx[1].get('Type', Variant('s', '')).value
                if name.lower() == "internet":
                    apn = ctx[1].get('AccessPointName', Variant('s', '')).value
                    auth_method = ctx[1].get('AuthenticationMethod', Variant('s', '')).value
                    username = ctx[1].get('Username', Variant('s', '')).value
                    password = ctx[1].get('Password', Variant('s', '')).value
                    if apn:
                        chosen_apn = apn
                        chosen_auth_method = auth_method
                        chosen_username = username
                        chosen_password = password

            new_properties = dict(self.props['Properties'].value)
            new_properties['apn'] = Variant('s', chosen_apn)
            new_properties['user'] = Variant('s', chosen_username)
            new_properties['password'] = Variant('s', chosen_password)

            if chosen_auth_method == 'none':
                new_properties['allowed-auth'] = Variant('u', 1) # none MM_BEARER_ALLOWED_AUTH_NONE
            elif chosen_auth_method == 'pap':
                new_properties['allowed-auth'] = Variant('u', 2) # pap MM_BEARER_ALLOWED_AUTH_PAP
            elif chosen_auth_method == 'chap':
                new_properties['allowed-auth'] = Variant('u', 3) # chap MM_BEARER_ALLOWED_AUTH_CHAP
            else:
                new_properties['allowed-auth'] = Variant('u', 0) # unknown MM_BEARER_ALLOWED_AUTH_UNKNOWN

            ofono_interface = self.ofono_client["ofono_modem"][self.modem_name]['org.ofono.ConnectionManager']

            roaming_allowed = None
            ofono_props = await ofono_interface.call_get_properties()

            roaming_allowed = ofono_props.get('RoamingAllowed', Variant('b', True)).value

            if read_setting('roaming').strip() != str(roaming_allowed):
                ofono2mm_print("Saving roaming toggle state", self.verbose)
                save_setting('roaming', str(roaming_allowed))

            if roaming_allowed == True:
                new_properties['roaming-allowance'] = Variant('u', 2) # roaming partner network MM_BEARER_ROAMING_ALLOWANCE_PARTNER
            elif roaming_allowed == False:
                new_properties['roaming-allowance'] = Variant('u', 0) # roaming none MM_BEARER_ROAMING_ALLOWANCE_NONE

            self.props['Properties'] = Variant('a{sv}', new_properties)

        changed_props = {}
        for prop in self.props:
            if self.props[prop].value != old_props[prop].value:
                changed_props.update({ prop: self.props[prop].value })

        if changed_props:
            self.emit_properties_changed(changed_props)

    @staticmethod
    def interface_is_up(interface):
        """Read IFF_UP, not carrier/operstate (cellular links may report unknown)."""
        if not interface or '/' in interface or interface in ('.', '..'):
            return None
        try:
            flags = int((Path('/sys/class/net') / interface / 'flags').read_text().strip(), base=16)
            return bool(flags & 1)
        except FileNotFoundError:
            return False
        except (OSError, ValueError):
            return None  # An unreadable link is not proof of a disconnect.

    def has_usable_config(self):
        interface = self.props['Interface'].value
        if not interface:
            return False
        if self.interface_is_up(interface) is False:
            return False

        # oFono supplies no IPv4 address on these modems, so either family satisfies this.
        return any([
            self.props['Ip4Config'].value.get('address'),
            self.props['Ip6Config'].value.get('address'),
        ])

    def set_ofono_context(self, path):
        if self.ofono_ctx == path and self._context_interface is not None:
            return
        self.close()
        self.ofono_ctx = path
        proxy = self.ofono_client['ofono_context'][path]['org.ofono.ConnectionContext']

        def changed(name, value):
            # Ignore queued signals after this context has been detached.
            if self._context_interface is proxy:
                self.ofono_context_changed(name, value)

        self._context_interface = proxy
        self._context_handler = changed
        proxy.on_property_changed(changed)

    def close(self):
        proxy, handler = self._context_interface, self._context_handler
        self._context_interface = self._context_handler = None
        if proxy is not None:
            proxy.off_property_changed(handler)

    @method()
    async def Connect(self):
        ofono2mm_print("Called bearer connect", self.verbose)
        self.active_connect += 1
        await self.doConnect()

    async def adopt_active_context(self, ofono_ctx_interface):
        """Take on the settings of a context that is already up, without touching it."""
        try:
            ctx_props = await ofono_ctx_interface.call_get_properties()
        except Exception as e:
            ofono2mm_print(f"Failed to read context properties: {e}", self.verbose)
            return False

        if not ctx_props.get('Active', Variant('b', False)).value:
            return False

        # A bearer only learns these from the signals that arrive while it exists.
        for propname in ('Settings', 'IPv6.Settings', 'Active'):
            if propname in ctx_props:
                self.ofono_context_changed(propname, ctx_props[propname])

        return self.has_usable_config()

    @async_retryable()
    async def activate_ofono_context(self, ofono_ctx_interface, protocol):
        # Re-activating a context that is already up would tear down a live PDN.
        if await self.adopt_active_context(ofono_ctx_interface):
            ofono2mm_print(f"oFono context {self.ofono_ctx} is already active on {self.props['Interface'].value}", self.verbose)
            return

        # The interface monitor must not mistake our own activation for a drop.
        self.disconnecting = True
        try:
            await asyncio.wait_for(
                ofono_ctx_interface.call_set_property("Active", Variant('b', False)),
                timeout=5.0)
            await ofono_ctx_interface.call_set_property("Protocol", Variant('s', protocol))
            await asyncio.wait_for(
                ofono_ctx_interface.call_set_property("Active", Variant('b', True)),
                timeout=ACTIVATE_TIMEOUT_SECONDS)
        except Exception as e:
            if "GPRS" in str(e):
                # no signal? wait a litle and try again
                ofono2mm_print(f"Failed to set context to active: {e}", self.verbose)
                await asyncio.sleep(5)
            else:
                ofono2mm_print(f"Failed to activate context: {e!r}", self.verbose)
            raise
        finally:
            self.disconnecting = False

    async def doConnect(self):
        ofono2mm_print(f"Connecting the bearer at path {self.own_object_path} with ofono context {self.ofono_ctx}", self.verbose)
        try:
            await self.set_props()
        except Exception as e:
            ofono2mm_print(f"Failed to set props: {e}", self.verbose)

        if not self.ofono_ctx:
            raise Exception("No oFono context set for bearer")

        ofono_ctx_interface = self._context_interface
        ofono2mm_print(f"Number of active connection requests: {self.active_connect}", self.verbose)

        protocol = read_setting("protocol", "ip").strip()
        ofono2mm_print(f"Activating bearer with protocol {protocol}", self.verbose)

        try:
            await self.activate_ofono_context(ofono_ctx_interface, protocol)

            # NetworkManager falls back to SLAAC without an address, and these modems
            # never answer a router solicitation.
            waited = 0.0
            while not self.has_usable_config() and waited < INTERFACE_WAIT_SECONDS:
                await asyncio.sleep(INTERFACE_POLL_SECONDS)
                waited += INTERFACE_POLL_SECONDS

            if not self.has_usable_config():
                raise Exception(f"oFono context {self.ofono_ctx} reported no usable configuration after activation")
        finally:
            # Release the slot on failure too, or one failed activation blocks every
            # later Connect() for this bearer.
            if self.active_connect >= 1:
                self.active_connect -= 1

        ofono2mm_print(f"Number of active connection requests: {self.active_connect}", self.verbose)

    @method()
    async def Disconnect(self):
        ofono2mm_print("Called bearer disconnect", self.verbose)
        await self.doDisconnect()

    async def doDisconnect(self):
        ofono2mm_print(f"Disconnecting the bearer at path {self.own_object_path} with ofono context {self.ofono_ctx}", self.verbose)
        self.disconnecting = True

        try:
            if not self.ofono_ctx:
                raise Exception("No oFono context set for bearer")
            await self._context_interface.call_set_property("Active", Variant('b', False))
        finally:
            self.disconnecting = False

    def ofono_context_changed(self, propname, value):
        ofono2mm_print(f"oFono context changed for prop name {propname} set to value {value}", self.verbose)

        old_props = deepcopy(self.props)

        if propname == "Active":
            if not value.value:
                # The name is only ever copied out of a populated Settings, so without
                # this it survives the deactivation.
                self.props['Interface'] = Variant('s', '')
                self.props['Ip4Config'] = Variant('a{sv}', {'method': Variant('u', 0)})
                self.props['Ip6Config'] = Variant('a{sv}', {'method': Variant('u', 0)})

            self.props['Connected'] = value
        elif propname == "Settings":
            if 'Interface' in value.value:
                self.props['Interface'] = value.value['Interface']
                if [value.value['Interface'].value, 2] not in self.mm_modem.props['Ports'].value:
                    self.mm_modem.props['Ports'].value.append([value.value['Interface'].value, 2]) # port type net MM_MODEM_PORT_TYPE_NET
                    self.mm_modem.emit_properties_changed({'Ports': self.mm_modem.props['Ports'].value})

            new_ip4 = {'method': Variant('u', 3)} # default dhcp MM_BEARER_IP_METHOD_DHCP

            if 'Method' in value.value:
                if value.value['Method'].value == 'static':
                    new_ip4['method'] = Variant('u', 2) # static MM_BEARER_IP_METHOD_STATIC
                if value.value['Method'].value == 'dhcp':
                    new_ip4['method'] = Variant('u', 3) # dhcp MM_BEARER_IP_METHOD_DHCP

            if 'Address' in value.value and value.value['Address'].value:
                new_ip4['address'] = value.value['Address']

            if 'Netmask' in value.value and value.value['Netmask'].value:
                new_ip4['prefix'] = Variant('u', netmask_to_prefix(value.value['Netmask'].value))

            if 'DomainNameServers' in value.value:
                ipv4_dns = []
                for dns in value.value['DomainNameServers'].value:
                    ipv4_dns.append(dns)

                for i in range(0, min(3, len(ipv4_dns))):
                    new_ip4['dns' + str(i + 1)] = Variant('s', ipv4_dns[i])
            if 'Gateway' in value.value and value.value['Gateway'].value:
                new_ip4['gateway'] = value.value['Gateway']

            self.props['Ip4Config'] = Variant('a{sv}', new_ip4)
        elif propname == "IPv6.Settings":
            new_ip6 = {'method': Variant('u', 3)} # default dhcp MM_BEARER_IP_METHOD_DHCP

            if 'Method' in value.value:
                if value.value['Method'].value == 'static':
                    new_ip6['method'] = Variant('u', 2) # static MM_BEARER_IP_METHOD_STATIC
                if value.value['Method'].value == 'dhcp':
                    new_ip6['method'] = Variant('u', 3) # dhcp MM_BEARER_IP_METHOD_DHCP
            elif 'Address' in value.value and value.value['Address'].value:
                new_ip6['method'] = Variant('u', 2) # static MM_BEARER_IP_METHOD_STATIC

            if 'Address' in value.value and value.value['Address'].value:
                new_ip6['address'] = value.value['Address']

            if 'PrefixLength' in value.value:
                new_ip6['prefix'] = Variant('u', value.value['PrefixLength'].value)

            if 'DomainNameServers' in value.value:
                ipv6_dns = []
                for dns in value.value['DomainNameServers'].value:
                    ipv6_dns.append(dns)

                for i in range(0, min(3, len(ipv6_dns))):
                    new_ip6['dns' + str(i + 1)] = Variant('s', ipv6_dns[i])
            if 'Gateway' in value.value and value.value['Gateway'].value:
                new_ip6['gateway'] = value.value['Gateway']

            self.props['Ip6Config'] = Variant('a{sv}', new_ip6)

        changed_props = {}
        for prop in self.props:
            if self.props[prop].value != old_props[prop].value:
                changed_props.update({ prop: self.props[prop].value })
        if changed_props:
            self.emit_properties_changed(changed_props)
        if propname == 'Active':
            # NetworkManager detects an unexpected modem CONNECTED -> REGISTERED
            # transition and applies its own retry/autoconnect policy.
            self.mm_modem.update_bearer_state()

    def ofono_changed(self, _name, _varval):
        asyncio.create_task(self.set_props())


class BearerConnectionMonitor:
    def __init__(self, modem, *, interval=2.0, grace=5.0, clock=monotonic,
                 link_is_up=MMBearerInterface.interface_is_up):
        self.modem = modem
        self.modem_name = modem.modem_name
        self.verbose = modem.verbose
        self.interval, self.grace = interval, grace
        self.clock, self.link_is_up = clock, link_is_up
        self.down_since = {}
        self.task = None

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self.run())

    def stop(self):
        if self.task is not None:
            self.task.cancel()
            self.task = None
        self.down_since.clear()

    async def run(self):
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self.check()
            except Exception as error:
                ofono2mm_print(f"Failed to check data interfaces: {error}", self.verbose)

    async def check(self):
        if not self.modem.enabled or self.modem.props['State'].value < ModemState.REGISTERED:
            self.down_since.clear()
            return
        contexts = {}
        for bearer in self.modem.bearers.values():
            if bearer.ofono_ctx:
                contexts.setdefault(bearer.ofono_ctx, []).append(bearer)

        down_contexts = {}
        for path, bearers in contexts.items():
            if any(bearer.disconnecting or bearer.active_connect for bearer in bearers):
                continue
            interfaces = {bearer.props['Interface'].value for bearer in bearers
                          if bearer.props['Connected'].value and bearer.props['Interface'].value}
            if any(self.link_is_up(interface) is False for interface in interfaces):
                down_contexts[path] = interfaces

        # Keep timers only for contexts that are still down and idle.
        self.down_since = {path: timer for path, timer in self.down_since.items()
                           if path in down_contexts}
        for path, interfaces in down_contexts.items():
            previous_interfaces, since = self.down_since.get(path, (None, self.clock()))
            if previous_interfaces != interfaces:
                self.down_since[path] = (interfaces, self.clock())
                continue
            if self.clock() - since >= self.grace:
                # One operation per oFono context, even if several MM bearers use it.
                self.down_since.pop(path, None)
                await self.modem.recover_bearer_context(path)
