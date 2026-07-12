import asyncio

from copy import deepcopy

from dbus_fast.service import ServiceInterface, method, dbus_property
from dbus_fast.constants import PropertyAccess
from dbus_fast import Variant

from ofono2mm.utils import async_retryable, save_setting, read_setting
from ofono2mm.logging import ofono2mm_print

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
        self.reconnect_task = None
        self.ofono_ctx = None
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

    @method()
    async def Connect(self):
        ofono2mm_print("Called bearer connect", self.verbose)
        self.active_connect += 1
        await self.doConnect()

    @async_retryable()
    async def doConnect(self):
        ofono2mm_print(f"Connecting the bearer at path {self.own_object_path} with ofono context {self.ofono_ctx}", self.verbose)
        try:
            await self.set_props()
        except Exception as e:
            ofono2mm_print(f"Failed to set props: {e}", self.verbose)

        if not self.ofono_ctx:
            raise Exception("No oFono context set for bearer")

        ofono_ctx_interface = self.ofono_client["ofono_context"][self.ofono_ctx]['org.ofono.ConnectionContext']
        ofono2mm_print(f"Number of active connection requests: {self.active_connect}", self.verbose)

        protocol = read_setting("protocol", "ip").strip()
        ofono2mm_print(f"Activating bearer with protocol {protocol}", self.verbose)

        # Mark this Active bounce as self-initiated so ofono_context_changed doesn't
        # mistake our own False->True cycle for an unexpected drop and spawn a
        # competing reconnect_task via network_manager_set_apn(force=True)
        self.disconnecting = True
        try:
            await asyncio.wait_for(ofono_ctx_interface.call_set_property("Active", Variant('b', False)), timeout=5.0)
            await ofono_ctx_interface.call_set_property("Protocol", Variant('s', protocol))
            await asyncio.wait_for(ofono_ctx_interface.call_set_property("Active", Variant('b', True)), timeout=5.0)
        except Exception as e:
            if "GPRS" in str(e):
                # no signal? wait a litle and try again
                ofono2mm_print(f"Failed to set context to active: {e}", self.verbose)
                await asyncio.sleep(5)
                raise Exception(str(e))
        finally:
            self.disconnecting = False

        if self.active_connect >= 1:
            self.active_connect -= 1

        # Clear the reconnection task
        self.reconnect_task = None
        ofono2mm_print(f"Number of active connection requests: {self.active_connect}", self.verbose)

    @method()
    async def Disconnect(self):
        ofono2mm_print("Called bearer disconnect", self.verbose)
        await self.doDisconnect()

    async def cancel_reconnect_task(self):
        if self.reconnect_task is not None:
            self.reconnect_task.cancel()
            try:
                await self.reconnect_task
            except asyncio.CancelledError:
                # Finally
                pass
            finally:
                self.reconnect_task = None

    async def doDisconnect(self):
        ofono2mm_print(f"Disconnecting the bearer at path {self.own_object_path} with ofono context {self.ofono_ctx}", self.verbose)
        self.disconnecting = True

        # Cancel an eventual reconnection task
        await self.cancel_reconnect_task()

        if not self.ofono_ctx:
            self.disconnecting = False
            raise Exception("No oFono context set for bearer")

        ofono_ctx_interface = self.ofono_client["ofono_context"][self.ofono_ctx]['org.ofono.ConnectionContext']
        await ofono_ctx_interface.call_set_property("Active", Variant('b', False))
        self.disconnecting = False

    def ofono_context_changed(self, propname, value):
        ofono2mm_print(f"oFono context changed for prop name {propname} set to value {value}", self.verbose)

        if propname == "Active":
            if self.disconnecting and value.value:
                self.disconnecting = False
            elif not self.disconnecting and (not value.value) and self.reconnect_task is None and self.props['Connected'].value:
                # Initiate a reconnection using NetworkManager.
                # TODO: ideally NM would take care of this itself once it learns that we lost the connection.

                self.reconnect_task = asyncio.create_task(self.mm_modem.mm_modem_simple_interface.network_manager_set_apn(force=True))

            self.props['Connected'] = value
            self.emit_properties_changed({'Connected': value.value})
        elif propname == "Settings":
            old_props = deepcopy(self.props)

            if 'Interface' in value.value:
                self.props['Interface'] = value.value['Interface']
                self.emit_properties_changed({'Interface': value.value['Interface'].value})
                if [value.value['Interface'].value, 2] not in self.mm_modem.props['Ports'].value:
                    self.mm_modem.props['Ports'].value.append([value.value['Interface'].value, 2]) # port type AT MM_MODEM_PORT_TYPE_AT
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
                octets = value.value['Netmask'].value.split('.')
                prefix = sum(bin(int(octet)).count('1') for octet in octets)
                new_ip4['prefix'] = Variant('u', prefix)

            if 'DomainNameServers' in value.value:
                ipv4_dns = []
                for dns in value.value['DomainNameServers'].value:
                    ipv4_dns.append(dns)

                for i in range(0, min(3, len(ipv4_dns))):
                    new_ip4['dns' + str(i + 1)] = Variant('s', ipv4_dns[i])
            if 'Gateway' in value.value and value.value['Gateway'].value:
                new_ip4['gateway'] = value.value['Gateway']

            self.props['Ip4Config'] = Variant('a{sv}', new_ip4)

            changed_props = {}
            for prop in self.props:
                if self.props[prop].value != old_props[prop].value:
                    changed_props.update({ prop: self.props[prop].value })
            if changed_props:
                self.emit_properties_changed(changed_props)
        elif propname == "IPv6.Settings":
            old_props = deepcopy(self.props)

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

    def ofono_changed(self, _name, _varval):
        asyncio.create_task(self.set_props())
