PROG := archivectl

PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/lib/$(PROG)
BASH_COMPLETIONS_DIR ?= $(PREFIX)/share/bash-completion/completions
FISH_COMPLETIONS_DIR ?= $(PREFIX)/share/fish/vendor_completions.d
ZSH_COMPLETIONS_DIR ?= $(PREFIX)/share/zsh/site-functions
MAN1DIR ?= $(PREFIX)/share/man/man1
MAN5DIR ?= $(PREFIX)/share/man/man5

install: $(PROG)
	install -d $(DESTDIR)$(BINDIR) $(DESTDIR)$(LIBDIR)
	sed 's|^INSTALLED_MODULE_DIR=.*|INSTALLED_MODULE_DIR="$(LIBDIR)"|' $(PROG) >$(DESTDIR)$(BINDIR)/.$(PROG).new
	chmod 755 $(DESTDIR)$(BINDIR)/.$(PROG).new
	mv -f $(DESTDIR)$(BINDIR)/.$(PROG).new $(DESTDIR)$(BINDIR)/$(PROG)
	install -m644 lib/common.sh libexec/$(PROG)/*.sh $(DESTDIR)$(LIBDIR)
	install -Dm644 completions/bash/$(PROG).bash $(DESTDIR)$(BASH_COMPLETIONS_DIR)/$(PROG)
	install -Dm644 completions/fish/$(PROG).fish $(DESTDIR)$(FISH_COMPLETIONS_DIR)/$(PROG).fish
	install -Dm644 completions/zsh/_$(PROG) $(DESTDIR)$(ZSH_COMPLETIONS_DIR)/_$(PROG)
	install -Dm644 man/$(PROG).1 $(DESTDIR)$(MAN1DIR)/$(PROG).1
	install -Dm644 man/$(PROG).5 $(DESTDIR)$(MAN5DIR)/$(PROG).5

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/$(PROG)
	rm -rf $(DESTDIR)$(LIBDIR)
	rm -f $(DESTDIR)$(BASH_COMPLETIONS_DIR)/$(PROG)
	rm -f $(DESTDIR)$(FISH_COMPLETIONS_DIR)/$(PROG).fish
	rm -f $(DESTDIR)$(ZSH_COMPLETIONS_DIR)/_$(PROG)
	rm -f $(DESTDIR)$(MAN1DIR)/$(PROG).1
	rm -f $(DESTDIR)$(MAN5DIR)/$(PROG).5

test:
	python3 -m pytest tests

.PHONY: install uninstall test
