PREFIX ?= /usr
LIBDIR ?= $(PREFIX)/lib
BINDIR ?= $(PREFIX)/bin
SBINDIR ?= $(PREFIX)/sbin
SYSTEMD_DIR = /usr/lib/systemd/system
POLKIT_DIR = /etc/polkit-1/localauthority/10-vendor.d
DBUS_DIR = /etc/dbus-1/system.d

MAIN = main.py
OFONO2MM_DIR = ofono2mm
DBUS_XML = dbus/dbus.xml dbus/ofono.xml dbus/ofono_modem.xml dbus/ofono_operator.xml dbus/ofono_context.xml
OFONOCTL = ofonoctl/ofonoctl

.PHONY: all install uninstall

all:
	@echo "Run 'make install' to install the files."

install:
	install -d $(DESTDIR)$(LIBDIR)/ofono2mm
	install -d $(DESTDIR)$(SBINDIR)
	install -d $(DESTDIR)$(BINDIR)
	install -m 755 $(MAIN) $(DESTDIR)$(LIBDIR)/ofono2mm/

	ln -sf ../lib/ofono2mm/$(MAIN) $(DESTDIR)$(SBINDIR)/ofono2mm
	cp -r $(OFONO2MM_DIR) $(DESTDIR)$(LIBDIR)/ofono2mm/

	install -m 644 $(DBUS_XML) $(DESTDIR)$(LIBDIR)/ofono2mm/
	install -m 755 $(OFONOCTL) $(DESTDIR)$(BINDIR)/ofonoctl

	install -d $(DESTDIR)$(SYSTEMD_DIR)/ModemManager.service.d
	install -m 644 systemd/10-ofono2mm.conf $(DESTDIR)$(SYSTEMD_DIR)/ModemManager.service.d/

	install -d $(DESTDIR)$(SYSTEMD_DIR)/NetworkManager.service.d
	install -m 0644 systemd/10-nm-restart.conf $(DESTDIR)$(SYSTEMD_DIR)/NetworkManager.service.d/

	install -d $(DESTDIR)$(POLKIT_DIR)
	install -m 644 extra/ofono2mm-radio.pkla $(DESTDIR)$(POLKIT_DIR)/

	install -d $(DESTDIR)$(DBUS_DIR)
	install -m 644 extra/org.freedesktop.ModemManager1.conf $(DESTDIR)$(DBUS_DIR)

uninstall:
	rm -rf $(DESTDIR)$(LIBDIR)/ofono2mm/
	rm -f $(DESTDIR)$(SBINDIR)/ofono2mm
	rm -f $(DESTDIR)$(BINDIR)/ofonoctl
	rm -f $(DESTDIR)$(SYSTEMD_DIR)/ModemManager.service.d/10-ofono2mm.conf
	rm -f $(DESTDIR)$(POLKIT_DIR)/ofono2mm-radio.pkla
	rm -f $(DESTDIR)$(DBUS_DIR)/org.freedesktop.ModemManager1.conf
