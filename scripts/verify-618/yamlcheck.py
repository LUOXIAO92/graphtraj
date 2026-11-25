import sys, yaml
class Strict(yaml.SafeLoader):
    pass
def construct_mapping(loader, node, deep=False):
    keys = set()
    for k, _ in node.value:
        key = loader.construct_object(k, deep=deep)
        if key in keys:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", k.start_mark)
        keys.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)
Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)
bad = 0
for path in sys.argv[1:]:
    try:
        doc = yaml.load(open(path, encoding='utf-8'), Loader=Strict)
        on = doc.get(True, doc.get('on'))  # YAML 1.1 reads bare 'on' as True
        print(f"OK   {path}: branches={on['push']['branches']}")
    except Exception as e:
        bad += 1
        print(f"FAIL {path}: {e}".replace('\n', ' '))
sys.exit(1 if bad else 0)
