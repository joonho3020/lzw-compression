

SNAPPY_CMD=snappy-cmd


BASEDIR=$(CURDIR)

SNAPPY_DIR=$(BASEDIR)/snappy
SNAPPY=snappy
SNAPPY_LIB=lib$(SNAPPY).a
SNAPPY_INSTALL_DIR=$(SNAPPY_DIR)/../snappy-install
SNAPPY_BUILD_DIR=$(SNAPPY_DIR)/build

all: $(SNAPPY_CMD)

$(SNAPPY_BUILD_DIR):
	mkdir -p $(SNAPPY_BUILD_DIR)

$(SNAPPY_INSTALL_DIR):
	mkdir -p $(SNAPPY_INSTALL_DIR)

$(SNAPPY_LIB): | $(SNAPPY_INSTALL_DIR) $(SNAPPY_BUILD_DIR)
	cd $(SNAPPY_BUILD_DIR) && cmake .. && make -j8 && make DESTDIR=../../snappy-install install

$(SNAPPY_CMD): $(SNAPPY_CMD).cc
	g++ -std=c++11 -o $@ $< -L$(SNAPPY_INSTALL_DIR)/usr/local/lib -l$(SNAPPY)

.PHONY: clean
clean:
	rm -rf $(SNAPPY_BUILD_DIR) $(SNAPPY_INSTALL_DIR) $(SNAPPY_CMD)
