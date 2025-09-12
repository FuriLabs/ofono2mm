from dbus_fast.service import (ServiceInterface,
                               method, dbus_property, signal)
from dbus_fast.constants import PropertyAccess
from dbus_fast import Variant

from ofono2mm.mm_sms import MMSmsInterface
from ofono2mm.logging import ofono2mm_print

message_i = 1

class MMModemMessagingInterface(ServiceInterface):
    def __init__(self, bus, modem_name, ofono_interfaces, verbose=False):
        super().__init__('org.freedesktop.ModemManager1.Modem.Messaging')
        self.modem_name = modem_name
        ofono2mm_print("Initializing Messaging interface", verbose)
        self.bus = bus
        self.ofono_interfaces = ofono_interfaces
        self.verbose = verbose
        self.props = {
            'Messages': Variant('ao', []),
            'SupportedStorages': Variant('au', []),
            'DefaultStorage': Variant('u', 0) # hardcoded value unknown MM_SMS_STORAGE_UNKNOWN
        }

    def init_messages(self):
        ofono2mm_print("Initializing signals", self.verbose)

        if 'org.ofono.MessageManager' in self.ofono_interfaces:
            self.ofono_interfaces['org.ofono.MessageManager'].on_incoming_message(self.add_incoming_message)
            self.ofono_interfaces['org.ofono.MessageManager'].on_immediate_message(self.add_incoming_message)
        else:
            ofono2mm_print("org.ofono.MessageManager was not available when initializing messaging", self.verbose)

    def add_incoming_message(self, msg, props):
        ofono2mm_print(f"Add incoming message {msg} with properties {props}", self.verbose)

        global message_i
        mm_sms_interface = MMSmsInterface(self.verbose)
        mm_sms_interface.props.update({
            'State': Variant('u', 3), # hardcoded value received MM_SMS_STATE_RECEIVED
            'PduType': Variant('u', 1), # hardcoded value deliver MM_SMS_PDU_TYPE_DELIVER
            'Number': props['Sender'],
            'Text': Variant('s', msg),
            'Timestamp': props['SentTime']
        })

        object_path = f'/org/freedesktop/ModemManager1/SMS/{message_i}'
        self.bus.export(object_path, mm_sms_interface)
        self.props['Messages'].value.append(object_path)
        self.emit_properties_changed({'Messages': self.props['Messages'].value})
        self.Added(object_path, True)
        message_i += 1

    @method()
    async def List(self) -> 'ao':
        ofono2mm_print("Returning list of messages", self.verbose)
        return self.props['Messages'].value

    @method()
    async def Delete(self, path: 'o'):
        ofono2mm_print(f"Delete message with object path {path}", self.verbose)

        if path in self.props['Messages'].value:
            self.props['Messages'].value.remove(path)
            self.bus.unexport(path)
            self.emit_properties_changed({'Messages': self.props['Messages'].value})
            self.Deleted(path)
        else:
            ofono2mm_print(f"{path} is not a valid object path", self.verbose)

    @method()
    async def Create(self, properties: 'a{sv}') -> 'o':
        ofono2mm_print(f"Create message with properties {properties}", self.verbose)

        global message_i
        if 'number' not in properties or 'text' not in properties:
            ofono2mm_print("Properties 'number' or 'text' are not available in properties", self.verbose)
            return

        mm_sms_interface = MMSmsInterface(self.verbose)
        mm_sms_interface.props.update({
            'Text': properties['text'],
            'Number': properties['number'],
            'DeliveryReportRequest': properties['delivery-report-request'] if 'delivery-report-request' in properties else Variant('b', False)
        })

        object_path = f'/org/freedesktop/ModemManager1/SMS/{message_i}'
        self.bus.export(object_path, mm_sms_interface)
        self.props['Messages'].value.append(object_path)
        self.emit_properties_changed({'Messages': self.props['Messages'].value})
        self.Added(object_path, True)
        message_i += 1

        if 'org.ofono.MessageManager' in self.ofono_interfaces:
            ofono_sms_object_path  = await self.ofono_interfaces['org.ofono.MessageManager'].call_send_message(properties['number'].value, properties['text'].value)
            ofono2mm_print(f"Created SMS with object path {ofono_sms_object_path}", self.verbose)
        else:
            ofono2mm_print(f"Failed to send message for {properties}. org.ofono.MessageManager is not available", self.verbose)

        return object_path

    @signal()
    def Added(self, path, received) -> 'ob':
        ofono2mm_print(f"Signal: Message added at object path {path} and received state {received}", self.verbose)
        return [path, received]

    @signal()
    def Deleted(self, path) -> 'o':
        ofono2mm_print(f"Signal: Message deleted at object path {path}", self.verbose)
        return path

    @dbus_property(access=PropertyAccess.READ)
    def Messages(self) -> 'ao':
        return self.props['Messages'].value

    @dbus_property(access=PropertyAccess.READ)
    def SupportedStorages(self) -> 'au':
        return self.props['SupportedStorages'].value

    @dbus_property(access=PropertyAccess.READ)
    def DefaultStorage(self) -> 'u':
        return self.props['DefaultStorage'].value
