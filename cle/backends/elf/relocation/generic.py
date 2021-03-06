import logging

from ....address_translator import AT
from ....errors import CLEOperationError, CLEInvalidBinaryError
from ... import SymbolType
from .elfreloc import ELFReloc

l = logging.getLogger(name=__name__)


class GenericTLSDoffsetReloc(ELFReloc):
    @property
    def value(self):
        return self.addend + self.symbol.relative_addr

    def resolve_symbol(self, solist, **kwargs):  #pylint: disable=unused-argument
        self.resolve(None)
        return True


class GenericTLSOffsetReloc(ELFReloc):
    AUTO_HANDLE_NONE = True

    def relocate(self):
        hell_offset = self.owner.arch.elf_tls.tp_offset

        if self.resolvedby is None:
            obj = self.owner
        else:
            obj = self.resolvedby.owner

        if obj.tls_block_offset is None:
            raise CLEInvalidBinaryError("Illegal relocation - dynamically loaded object using static TLS")

        self.owner.memory.pack_word(
            self.relative_addr,
            obj.tls_block_offset + self.addend + self.symbol.relative_addr - hell_offset)


class GenericTLSModIdReloc(ELFReloc):
    AUTO_HANDLE_NONE = True

    def relocate(self):
        if self.symbol.type == SymbolType.TYPE_NONE:
            obj = self.owner
        else:
            obj = self.resolvedby.owner

        self.owner.memory.pack_word(self.relative_addr, obj.tls_module_id)


class GenericIRelativeReloc(ELFReloc):
    AUTO_HANDLE_NONE = True

    def relocate(self):
        if self.symbol.type == SymbolType.TYPE_NONE:
            self.owner.irelatives.append((AT.from_lva(self.addend, self.owner).to_mva(), self.relative_addr))
        else:
            self.owner.irelatives.append((self.resolvedby.rebased_addr, self.relative_addr))


class GenericAbsoluteAddendReloc(ELFReloc):
    @property
    def value(self):
        return self.resolvedby.rebased_addr + self.addend


class GenericPCRelativeAddendReloc(ELFReloc):
    @property
    def value(self):
        return self.resolvedby.rebased_addr + self.addend - self.rebased_addr


class GenericJumpslotReloc(ELFReloc):
    @property
    def value(self):
        if self.is_rela:
            return self.resolvedby.rebased_addr + self.addend
        else:
            return self.resolvedby.rebased_addr


class GenericRelativeReloc(ELFReloc):
    AUTO_HANDLE_NONE = True

    @property
    def value(self):
        if self.resolvedby is not None:
            return self.resolvedby.rebased_addr
        return self.owner.mapped_base + self.addend


class GenericAbsoluteReloc(ELFReloc):
    @property
    def value(self):
        return self.resolvedby.rebased_addr


class GenericCopyReloc(ELFReloc):
    def resolve_symbol(self, solist, **kwargs):
        new_solist = [x for x in solist if x is not self.owner]
        super().resolve_symbol(new_solist, **kwargs)

    def relocate(self):
        if self.resolvedby.size != self.symbol.size and (self.resolvedby.size != 0 or not self.resolvedby.is_extern):
            l.error("Export symbol is different size than import symbol for copy relocation: %s", self.symbol.name)
        else:
            self.owner.memory.store(self.relative_addr, self.resolvedby.owner.memory.load(self.resolvedby.relative_addr, self.resolvedby.size))
        return True


class MipsGlobalReloc(GenericAbsoluteReloc):
    pass


class MipsLocalReloc(ELFReloc):
    AUTO_HANDLE_NONE = True

    def resolve_symbol(self, solist, **kwargs):
        self.resolve(None)

    def relocate(self):
        if self.owner.mapped_base == 0:
            return   # don't touch local relocations on the main bin

        delta = self.owner.mapped_base - self.owner._dynamic['DT_MIPS_BASE_ADDRESS']
        if delta == 0:
            return

        val = self.owner.memory.unpack_word(self.relative_addr)
        newval = val + delta
        self.owner.memory.pack_word(self.relative_addr, newval)


class RelocTruncate32Mixin:
    """
    A mix-in class for relocations that cover a 32-bit field regardless of the architecture's address word length.
    """

    # If True, 32-bit truncated value must equal to its original when zero-extended
    check_zero_extend = False

    # If True, 32-bit truncated value must equal to its original when sign-extended
    check_sign_extend = False

    def relocate(self):
        arch_bits = self.owner.arch.bits
        assert arch_bits >= 32            # 16-bit makes no sense here

        val = self.value % (2**arch_bits)   # we must truncate it to native range first

        if (self.check_zero_extend and val >> 32 != 0 or
                self.check_sign_extend and val >> 32 != ((1 << (arch_bits - 32)) - 1)
                                                        if ((val >> 31) & 1) == 1 else 0):
            raise CLEOperationError("relocation truncated to fit: %s; consider making"
                                    " relevant addresses fit in the 32-bit address space." % self.__class__.__name__)

        self.owner.memory.pack_word(self.dest_addr, val, size=4, signed=False)

        return True
