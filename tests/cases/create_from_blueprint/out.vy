@external
@nonpayable
def func_0(x_BYTESM_0: bytes32) -> address:
    x_ADDRESS_0: address = create_from_blueprint(0x1337000000000000000000000000000000000000, raw_args = False, value = 0, code_offset = 0, salt = x_BYTESM_0)
    return x_ADDRESS_0

