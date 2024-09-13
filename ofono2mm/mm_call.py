from dbus_fast.service import ServiceInterface, method, dbus_property, signal
from dbus_fast.constants import PropertyAccess
from dbus_fast import Variant

from ofono2mm.logging import ofono2mm_print

class MMCallInterface(ServiceInterface):
    def __init__(self, ofono_client, ofono_interfaces, verbose=False):
        super().__init__('org.freedesktop.ModemManager1.Call')
        ofono2mm_print("Initializing Call interface", verbose)
        self.ofono_client = ofono_client
        self.ofono_interfaces = ofono_interfaces
        self.verbose = verbose
        self.voicecall = '/'
        self.ofono_voicecall = None
        self.props = {
            'State': Variant('i', 0), # on runtime unknown MM_CALL_STATE_UNKNOWN
            'StateReason': Variant('i', 0), # on runtime unknown MM_CALL_STATE_REASON_UNKNOWN
            'Direction': Variant('i', 0), # on runtime unknown MM_CALL_DIRECTION_UNKNOWN
            'Number': Variant('s', ''),
            'Multiparty': Variant('b', False),
            'AudioPort': Variant('s', ''),
            'AudioFormat': Variant('a{sv}', {
                "encoding": Variant('s', 'pcm'),
                "resolution": Variant('s', 's16le'),
                "rate": Variant('i', 48000),
            })
        }

    def init_call(self):
        ofono2mm_print(f"Initializing call {self.voicecall}", self.verbose)
        self.ofono_voicecall = self.ofono_client["ofono_modem"][self.voicecall]['org.ofono.VoiceCall']
        self.ofono_voicecall.on_property_changed(self.property_changed)

    def property_changed(self, property, value):
        ofono2mm_print(f"Voice Call {self.voicecall} property {property} changed to {value}", self.verbose)

        if property == "State":
            if value.value == "active":
                old_state = self.props['State'].value
                new_state = 4 # active MM_CALL_STATE_ACTIVE
                reason = 3 # accepted MM_CALL_STATE_REASON_ACCEPTED
                self.props['State'] = Variant('i', new_state)
                self.StateChanged(old_state, new_state, reason)

    @method()
    def Start(self):
        ofono2mm_print("Starting call", self.verbose)
        old_state = self.props['State'].value
        new_state = 4 # active MM_CALL_STATE_ACTIVE
        reason = 1 # outgoing started MM_CALL_STATE_REASON_OUTGOING_STARTED
        self.props['State'] = Variant('i', new_state)
        self.props['StateReason'] = Variant('i', reason)
        self.StateChanged(old_state, new_state, reason)

    @method()
    async def Accept(self):
        ofono2mm_print("Accepting call", self.verbose)
        await self.ofono_voicecall.call_answer()
        old_state = self.props['State'].value
        new_state = 4 # active MM_CALL_STATE_ACTIVE
        reason = 3 # outgoing started MM_CALL_STATE_REASON_ACCEPTED
        self.props['State'] = Variant('i', new_state)
        self.props['StateReason'] = Variant('i', reason)
        self.StateChanged(old_state, new_state, reason)

    @method()
    async def Deflect(self, number: 's'):
        ofono2mm_print(f"Deflecting number {number}", self.verbose)
        await self.ofono_voicecall.call_deflect(number)
        old_state = self.props['State'].value
        new_state = 7 # terminated MM_CALL_STATE_TERMINATED
        reason = 9 # deflected MM_CALL_STATE_REASON_DEFLECTED
        self.props['StateReason'] = Variant('i', reason)
        self.StateChanged(old_state, new_state, reason)

    @method()
    async def JoinMultiparty(self):
        ofono2mm_print("Joining multiparty", self.verbose)
        await self.ofono_interfaces['org.ofono.VoiceCallManager'].call_create_multiparty()
        self.props['Multiparty'] = Variant('b', True)

    @method()
    async def LeaveMultiparty(self):
        ofono2mm_print("Leaving multiparty", self.verbose)
        await self.ofono_interfaces['org.ofono.VoiceCallManager'].call_hangup_multiparty()
        self.props['Multiparty'] = Variant('b', False)

    @method()
    async def Hangup(self):
        ofono2mm_print("Hanging up call", self.verbose)

        try:
            await self.ofono_voicecall.call_hangup()
        except Exception as e:
            ofono2mm_print(f"Failed to hang up call: {e}", self.verbose)
            ofono2mm_print("Calling hang up all instead", self.verbose)
            await self.ofono_interfaces['org.ofono.VoiceCallManager'].call_hangup_all()

        old_state = self.props['State'].value
        new_state = 7 # terminated MM_CALL_STATE_TERMINATED
        reason = 4 # terminated MM_CALL_STATE_REASON_TERMINATED
        self.props['State'] = Variant('i', new_state)
        self.props['StateReason'] = Variant('i', reason)
        self.StateChanged(old_state, new_state, reason)

    @method()
    async def SendDtmf(self, dtmf: 's'):
        ofono2mm_print(f"Send dtmf {dtmf}", self.verbose)
        await self.ofono_interfaces['org.ofono.VoiceCallManager'].call_send_tones(dtmf)

    @signal()
    def DtmfReceived(self, dtmf) -> 's':
        ofono2mm_print(f"Dtmf {dtmf} received", self.verbose)
        return dtmf

    @signal()
    def StateChanged(self, old, new, reason) -> 'iiu':
        ofono2mm_print(f"State changed from {old} to {new} for reason {reason}", self.verbose)
        return [old, new, reason]

    @dbus_property(access=PropertyAccess.READ)
    def State(self) -> 'i':
        return self.props['State'].value

    @dbus_property(access=PropertyAccess.READ)
    def StateReason(self) -> 'i':
        return self.props['StateReason'].value

    @dbus_property(access=PropertyAccess.READ)
    def Direction(self) -> 'i':
        return self.props['Direction'].value

    @dbus_property(access=PropertyAccess.READ)
    def Number(self) -> 's':
        return self.props['Number'].value

    @dbus_property(access=PropertyAccess.READ)
    def Multiparty(self) -> 'b':
        return self.props['Multiparty'].value

    @dbus_property(access=PropertyAccess.READ)
    def AudioPort(self) -> 's':
        return self.props['AudioPort'].value

    @dbus_property(access=PropertyAccess.READ)
    def AudioFormat(self) -> 'a{sv}':
        return self.props['AudioFormat'].value
