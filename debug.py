with open("test_file.ts", "w") as f:
    f.write("describe('my suite', () => {\n  it('does A', () => {});\n});\n")
with open("test_file.ts", "r") as f:
    print(repr(f.read()))
