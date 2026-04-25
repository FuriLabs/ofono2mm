import multiprocessing
from datetime import datetime
from os import seteuid, getuid, chown, makedirs
from os.path import join
import asyncio

import gi
gi.require_version('Geoclue', '2.0')
from gi.repository import GLib, Geoclue

from dbus_fast.service import ServiceInterface, method, dbus_property
from dbus_fast.constants import PropertyAccess
from dbus_fast import Variant, DBusError

from ofono2mm.logging import ofono2mm_print

simple = None
main_loop = None
location_data = None
verbose = False

def on_simple_ready(_source_object, result, _user_data):
    global simple, main_loop, location_data, verbose
    ofono2mm_print("Geoclue got location", verbose)

    try:
        simple = Geoclue.Simple.new_with_thresholds_finish(result)
        if not simple:
            location_data = None
            if main_loop:
                main_loop.quit()
            return

        location = simple.get_location()
        longitude = location.get_property('longitude')
        latitude = location.get_property('latitude')
        altitude = location.get_property('altitude')

        location_data = (latitude, longitude, altitude)
    except Exception:
        location_data = None
    finally:
        if main_loop:
            main_loop.quit()

def on_timeout(_user_data):
    global simple, main_loop, location_data, verbose
    ofono2mm_print("Geoclue timeout reached", verbose)

    try:
        if simple:
            try:
                client = simple.get_client()
                if client:
                    client.stop()
                    client.set_property('active', False)
                    client = None
            except Exception as e:
                ofono2mm_print(f"Failed to stop geoclue client: {e}", verbose)
            simple = None
        location_data = None
    finally:
        if main_loop and main_loop.is_running():
            GLib.idle_add(main_loop.quit)
    return False

def _geoclue_process_func(queue):
    global simple, main_loop, location_data, verbose

    try:
        seteuid(32011)
        GLib.timeout_add_seconds(30, on_timeout, None)

        Geoclue.Simple.new_with_thresholds("ModemManager",
                                           Geoclue.AccuracyLevel.EXACT,
                                           0, 0, None, on_simple_ready, None)

        main_loop = GLib.MainLoop()
        main_loop.run()

        if simple:
            try:
                client = simple.get_client()
                if client:
                    client.stop()
                    client.set_property('active', False)
                    client = None
            except Exception as e:
                ofono2mm_print(f"Failed to stop geoclue client: {e}", verbose)
            simple = None

        if location_data:
            queue.put(('result', location_data))
        else:
            queue.put(('error', "Failed to get location data."))
    except Exception as e:
        queue.put(('error', str(e)))
    finally:
        if getuid() == 0:
            seteuid(0)

async def async_geoclue_get_location():
    queue = multiprocessing.Queue()

    process = multiprocessing.Process(target=_geoclue_process_func, args=(queue,))
    process.start()

    while process.is_alive():
        await asyncio.sleep(0.1)

    try:
        status, data = queue.get_nowait()
        if status == 'error':
            raise Exception(data)
        return data
    except multiprocessing.queues.Empty:
        raise Exception("No result received from Geoclue process")
    finally:
        if process.is_alive():
            process.terminate()
        process.join()
        queue.close()

class MMModemLocationInterface(ServiceInterface):
    def __init__(self, modem_name, verbose=False):
        super().__init__('org.freedesktop.ModemManager1.Modem.Location')
        self.modem_name = modem_name
        ofono2mm_print("Initializing Location interface", verbose)
        self.verbose = verbose
        utc_time = datetime.utcnow().isoformat()
        self.config_dir = '/etc/geoclue/conf.d'
        self.config_path = join(self.config_dir, 'supl.conf')
        self.owner_uid = 32011
        self.owner_gid = 32011

        self.location = {
            2: Variant('a{sv}', { # 2 is MM_MODEM_LOCATION_SOURCE_GPS_RAW
                'utc-time': Variant('s', utc_time),
                'latitude': Variant('d', 0),
                'longitude': Variant('d', 0),
                'altitude': Variant('d', 0)
            })
        }

        self.props = {
            'Capabilities': Variant('u', 2), # hardcoded dummy value raw MM_MODEM_LOCATION_SOURCE_GPS_RAW
            'SupportedAssistanceData': Variant('u', 0), # hardcoded dummy value none MM_MODEM_LOCATION_ASSISTANCE_DATA_TYPE_NONE
            'Enabled': Variant('u', 2), # hardcoded dummy value raw MM_MODEM_LOCATION_SOURCE_GPS_RAW
            'SignalsLocation': Variant('b', False),
            'SuplServer': Variant('s', ''),
            'AssistanceDataServers': Variant('as', []),
            'GpsRefreshRate': Variant('u', 0)
        }

    @method()
    def Setup(self, sources: 'u', signal_location: 'b') -> None:
        ofono2mm_print(f"Setup location with source flag {sources} and signal location {signal_location}", self.verbose)
        self.props['Enabled'] = Variant('u', sources)
        self.props['SignalsLocation'] = Variant('b', signal_location)
        self.emit_properties_changed({
            'Enabled': self.props['Enabled'].value,
            'SignalsLocation': self.props['SignalsLocation'].value
        })

    @method()
    async def GetLocation(self) -> 'a{uv}':
        ofono2mm_print("Returning current location", self.verbose)

        global verbose
        verbose = self.verbose

        try:
            latitude, longitude, altitude = await async_geoclue_get_location()
        except Exception as e:
            ofono2mm_print(f"Failed to get location from geoclue: {e}", self.verbose)
            longitude = 0
            latitude = 0
            altitude = 0

        utc_time = datetime.utcnow().isoformat()

        ofono2mm_print(f"Location is longitude: {longitude}, latitude: {latitude}, altitude: {altitude}", self.verbose)

        location_variant = self.location[2].value
        location_variant['utc-time'] = Variant('s', utc_time)
        location_variant['latitude'] = Variant('d', latitude)
        location_variant['longitude'] = Variant('d', longitude)
        location_variant['altitude'] = Variant('d', altitude)

        return self.location

    @method()
    def SetSuplServer(self, supl: 's'):
        try:
            makedirs(self.config_dir, exist_ok=True)
        except OSError as e:
            raise DBusError('org.freedesktop.ModemManager1.Error.Core.Failed', f'Failed to create configuration directory: {e}')

        config_content = f"""[hybris]
supl-enabled=true
supl-server={supl}
"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as config_file:
                config_file.write(config_content)
        except IOError as e:
            raise DBusError('org.freedesktop.ModemManager1.Error.Core.Failed', f'Failed to write SUPL server configuration: {e}')

        try:
            chown(self.config_dir, self.owner_uid, self.owner_gid)
            chown(self.config_path, self.owner_uid, self.owner_gid)
        except OSError as e:
            raise DBusError('org.freedesktop.ModemManager1.Error.Core.Failed', f'Failed to change ownership of configuration: {e}')

        self.props['SuplServer'] = Variant('s', supl)
        self.emit_properties_changed({'SuplServer': self.props['SuplServer'].value})

    @method()
    def InjectAssistanceData(self, data: 'ay') -> None:
        raise DBusError('org.freedesktop.ModemManager1.Error.Core.Unsupported', 'Cannot inject assistance data: unsupported')

    @method()
    def SetGpsRefreshRate(self, rate: 'u') -> None:
        ofono2mm_print(f"Setting GPS refresh rate to {rate}", self.verbose)
        self.props['GpsRefreshRate'] = Variant('u', rate)
        self.emit_properties_changed({'GpsRefreshRate': self.props['GpsRefreshRate'].value})

    @dbus_property(access=PropertyAccess.READ)
    def Capabilities(self) -> 'u':
        return self.props['Capabilities'].value

    @dbus_property(access=PropertyAccess.READ)
    def SupportedAssistanceData(self) -> 'u':
        return self.props['SupportedAssistanceData'].value

    @dbus_property(access=PropertyAccess.READ)
    def Enabled(self) -> 'u':
        return self.props['Enabled'].value

    @dbus_property(access=PropertyAccess.READ)
    def SignalsLocation(self) -> 'b':
        return self.props['SignalsLocation'].value

    @dbus_property(access=PropertyAccess.READ)
    def Location(self) -> 'a{uv}':
        return self.location

    @dbus_property(access=PropertyAccess.READ)
    def SuplServer(self) -> 's':
        return self.props['SuplServer'].value

    @dbus_property(access=PropertyAccess.READ)
    def AssistanceDataServers(self) -> 'as':
        return self.props['AssistanceDataServers'].value

    @dbus_property(access=PropertyAccess.READ)
    def GpsRefreshRate(self) -> 'u':
        return self.props['GpsRefreshRate'].value
