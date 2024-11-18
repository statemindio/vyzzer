import atheris

from run_api import GeneratorBase

with atheris.instrument_imports():
    import vyper
    from fuzz.converters.typed_converters_4 import NaginiConverter


class GeneratorNagini(GeneratorBase):
    def compile_source(self, proto_result):
        try:
            c_result = vyper.compile_code(proto_result)
            return c_result, None
        except Exception as e:
            return None, e


generator = GeneratorNagini(NaginiConverter)

if __name__ == '__main__':
    generator.start_generator()
