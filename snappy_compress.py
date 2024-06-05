



from collections import defaultdict

data_file = open("../software/benchmarks/silesia/xml", 'rb')
input_data = data_file.read()
data_file.close()
input_data_byte_arr = [ input_data[x] for x in range(len(input_data)) ]
#print(len(input_data_byte_arr))
del input_data

kMaxHashTableBits = 14
kHashTableBytes = 1 << kMaxHashTableBits


def slice_to_int(slice_in):
    if len(slice_in) != 4:
        new_slice = [0, 0, 0, 0]
        for x in range(len(slice_in)):
            new_slice[x] = slice_in[x]
        slice_in = new_slice

    a = 0
    a |= slice_in[0]
    a |= slice_in[1] << 8
    a |= slice_in[2] << 16
    a |= slice_in[3] << 24
    return a

def int_to_slice(int_in):
    out = []
    out.append(int_in & 0xFF)
    int_in >>= 8
    out.append(int_in & 0xFF)
    int_in >>= 8
    out.append(int_in & 0xFF)
    int_in >>= 8
    out.append(int_in & 0xFF)
    return out

def hashfn(four_byte_input_int):
    """
    inline uint32_t HashBytes(uint32_t bytes, uint32_t mask) {
        constexpr uint32_t kMagic = 0x1e35a7bd;
        return ((kMagic * bytes) >> (32 - kMaxHashTableBits)) & mask;
    }

    """
    four_byte_mask_int = kHashTableBytes - 1
    kMagic = 0x1e35a7bd
    return ((kMagic * four_byte_input_int) >> (32 - kMaxHashTableBits)) & four_byte_mask_int

class HistoryBuffer:

    def __init__(self):
        self.history = [b"" for x in range(64 << 10)]

    def insert_head(self, values_slice, length):
        if type(values_slice) == int:
            values_slice = [values_slice]
        c = values_slice.copy()
        c.reverse()
        self.history = c + self.history[:-length]


    def check_match_len(self, values_slice, offset):
        if offset < 0:
            return 0
        h = self.history[:offset].copy()
        h.reverse()

        min_len = min(len(h), len(values_slice))
        #print("comparing")
        #print(h)
        #print(values_slice)
        returnlen = 0
        for x in range(min_len):
            if values_slice[x] != h[x]:
                return [returnlen, False]
            returnlen += 1
        return [returnlen, min_len == len(h)]





class HashTable:

    def __init__(self):
        # table is indexed by hashing 4 bytes
        # each entry holds a hash (with a different FN) of the next 4, 8, 16B and N copies of them
        # replacement policy is random to start with
        #
        # this verison is just regular snappy: 64 bit abs addr
        self.hashtable = [-1 for x in range(2 ** kMaxHashTableBits)]


    def hash_lookup(self, input_slice):
        as_int = slice_to_int(input_slice)
        hashed = hashfn(as_int)
        return self.hashtable[hashed]

    def hash_set(self, input_slice, abs_addr):
        as_int = slice_to_int(input_slice)
        hashed = hashfn(as_int)
        self.hashtable[hashed] = abs_addr

outputcmds = []

index_ptr = 0
emit_so_far = 0

ht = HashTable()
hb = HistoryBuffer()

lit_emit_queue = []


# we're not going to implement "skipping" beyond 16B (i.e. 32 * 16 = 512B seen
# without match) because it doesn't make
# sense when we can do hash lookups inline with reading the data (i.e. we need
# to load the data once anyway, so might as well do the hash lookup)
#
# this slightly complicates the ability to determine literal length easily:
# skipping would mean that we would read random points ahead to find the match,
# then do a separate "memcopy" in the accelerator, which means we could
# know the literal length ahead of time.
#
# our literal scheme:
# buffer up to 1024B of output. this means (tag len includes length):
# lit len               | old tag len | new tag len | worst overhead
# 0B to 60B             |          1B | 1B          | 0%
# 61B to 256B           |          2B | 2B          | 0%
# 256B to 1024B         |          3B | 3B          | 0%
# 1025B to 65536B       |          3B | 5B          | 0.195%
# 65537B to 2^24B       |          4B | 5B          | 0.00153%
# (2^24 + 1)B to 2^32B  |          5B | 5B          | 0%


### Other "free" stuff:
# 1) could update hash table every "beat" during long copy identification
# 2) don't need to "skip" as much --- there's no point in not checking once
# every 16B

skip = 32

while index_ptr + 3 < len(input_data_byte_arr):
    if index_ptr % 1000 == 0:
        print(index_ptr)
    next_advance = min(skip >> 5, 16)
    dat_4 = input_data_byte_arr[index_ptr:index_ptr+4]
    dat_up_to_16 = input_data_byte_arr[index_ptr:index_ptr+min(16, len(input_data_byte_arr) - index_ptr)]
    lookup = ht.hash_lookup(dat_4)
    ht.hash_set(dat_4, index_ptr)

    if lookup == -1:
        hb.insert_head(input_data_byte_arr[index_ptr:index_ptr+next_advance], next_advance)
        lit_emit_queue.append(input_data_byte_arr[index_ptr:index_ptr+next_advance])
        #print("emit lit no hash", input_data_byte_arr[index_ptr:index_ptr+next_advance])
        index_ptr += next_advance
        skip += next_advance
        continue

    match_len, continue_match_check = hb.check_match_len(dat_up_to_16, index_ptr - lookup)
    if match_len == 0:
        hb.insert_head(input_data_byte_arr[index_ptr:index_ptr+next_advance], next_advance)
        lit_emit_queue.append(input_data_byte_arr[index_ptr:index_ptr+next_advance])
        #print("emit lit no strmatch", input_data_byte_arr[index_ptr:index_ptr+next_advance])
        index_ptr += next_advance
        skip += next_advance
        continue

    # emit any literals up to this point
    if len(lit_emit_queue) != 0:
        outputcmds.append({"op": "LITERAL", "litvals": lit_emit_queue})
        #print("found match emit lit cmd", lit_emit_queue)
        lit_emit_queue = []


    if match_len != 16 and not continue_match_check:
            hb.insert_head(dat_up_to_16[:match_len], match_len)
            outputcmds.append({"op": "COPY", "offset": index_ptr - lookup, "length": match_len})
            index_ptr += match_len
            skip = 32
            continue

    index_ptr += match_len
    lookup += match_len
    hb.insert_head(dat_up_to_16[:match_len], match_len)

    while index_ptr < len(input_data_byte_arr):
        dat_up_to_16_2 = input_data_byte_arr[index_ptr:index_ptr+min(16, len(input_data_byte_arr) - index_ptr)]
        match_len_2, continue_match_check2 = hb.check_match_len(dat_up_to_16_2, index_ptr - (lookup))
        match_len += match_len_2
        lookup += match_len_2
        index_ptr += match_len_2
        if match_len_2 == 0:
            break
        hb.insert_head(dat_up_to_16_2[:match_len_2], match_len_2)
        if match_len_2 != 16 and not continue_match_check2:
            break



    minus_one_dat = input_data_byte_arr[index_ptr-1:index_ptr-1+4]
    ht.hash_set(minus_one_dat, index_ptr-1)

    skip = 32
    outputcmds.append({"op": "COPY", "offset": index_ptr - lookup, "length": match_len})


if len(lit_emit_queue) != 0 or index_ptr != len(input_data_byte_arr):
    extra_dat = input_data_byte_arr[index_ptr:len(input_data_byte_arr)]
    if isinstance(extra_dat, int):
        extra_dat = list(extra_dat)
    lit_emit_queue += list(map(lambda x: [x], extra_dat))
    outputcmds.append({"op": "LITERAL", "litvals": lit_emit_queue})
    lit_emit_queue = []

#for cmd in outputcmds:
    #print(cmd)

OUTPUT_DATA = b""

uncomp_len = len(input_data_byte_arr)

while uncomp_len & 0x7F:
    more = False
    orval = 0
    if (uncomp_len >> 7) & 0x7F:
        more = True
        orval = 1 << 7
    OUTPUT_DATA += bytes([(uncomp_len & 0x7F) | orval])
    uncomp_len >>= 7

#print(OUTPUT_DATA)
print("numcmds:")
print(len(outputcmds))

for cmdno, cmd in enumerate(outputcmds):
    if cmdno % 100 == 0:
        print(cmdno)
    if cmd['op'] == "LITERAL":
        litlen = len(cmd['litvals'])
        if litlen <= 60:
            OUTPUT_DATA += bytes([(litlen-1) << 2])
        elif litlen <= 256:
            OUTPUT_DATA += bytes([(60 << 2)])
            OUTPUT_DATA += bytes([(litlen - 1)])
        elif litlen <= 1024:
            OUTPUT_DATA += bytes([(61 << 2)])
            OUTPUT_DATA += bytes([(litlen - 1) & 0xFF])
            OUTPUT_DATA += bytes([((litlen - 1) >> 8) & 0xFF])
        else:
            OUTPUT_DATA += bytes([(63 << 2)])
            OUTPUT_DATA += bytes([(litlen - 1) & 0xFF])
            OUTPUT_DATA += bytes([((litlen - 1) >> 8) & 0xFF])
            OUTPUT_DATA += bytes([((litlen - 1) >> 16) & 0xFF])
            OUTPUT_DATA += bytes([((litlen - 1) >> 24) & 0xFF])
        for delem in cmd['litvals']:
            OUTPUT_DATA += bytes([delem[0]])

    elif cmd['op'] == "COPY":
        offset = cmd['offset']
        length = cmd['length']

        if length <= 11 and length >= 4 and offset <= 2047:
            OUTPUT_DATA += bytes([
                1 | (((length - 4) & 0x7) << 2) | (((offset >> 8) & 0x7) << 5),
                offset & 0xFF
            ])
        elif length <= 64 and length >= 1 and offset <= 65535:
            OUTPUT_DATA += bytes([
                1 | (((length - 1) & 0x3F) << 2),
                offset & 0xFF,
                (offset >> 8) & 0xFF
            ])
        else:
            OUTPUT_DATA += bytes([
                1 | (((length - 1) & 0x3F) << 2),
                offset & 0xFF,
                (offset >> 8) & 0xFF,
                (offset >> 16) & 0xFF,
                (offset >> 24) & 0xFF
            ])


#print(OUTPUT_DATA)
print(len(OUTPUT_DATA))

