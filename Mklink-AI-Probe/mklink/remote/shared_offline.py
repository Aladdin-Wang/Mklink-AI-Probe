"""Translate opaque remote uploads to the existing local deployment form."""
import json
from mklink.remote.protocol import RequestValidationError


def deployment_form(params, uploads):
    from mklink.remote.dispatcher import _remote_offline_config, _mapping, _text
    from mklink.offline_download import parse_offline_config
    if params.keys() - {'config', 'firmware_files', 'algorithm_files', 'confirm', 'request_id'}:
        raise RequestValidationError('Unsupported offline deployment parameters')
    request_id = params.get('request_id')
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        raise RequestValidationError('A stable request_id is required for deployment')
    config = _remote_offline_config(params.get('config'))
    # Never permit a remote request to supply field-machine paths or profile tokens.
    algorithms = []
    for raw in config.get('algorithms', []):
        row = dict(_mapping(raw, 'algorithm'))
        if row.get('source_path') or row.get('source_token') or row.get('source_kind', 'upload') != 'upload':
            raise RequestValidationError('Remote algorithms require opaque uploads')
        algorithms.append(row)
    config['algorithms'] = algorithms
    parsed = parse_offline_config(config)
    for field, entries, rows in (
        ('firmware_files', parsed.firmwares, config['firmwares']),
        ('algorithm_files', parsed.algorithms, config['algorithms']),
    ):
        refs = _mapping(params.get(field, {}), field)
        if set(refs) != {item.id for item in entries}:
            raise RequestValidationError('Upload references must match configured IDs', data={'field': field})
        for item, row in zip(entries, rows):
            row.pop('upload_index', None)
            row['source_path'] = str(uploads.resolve(_text(refs[item.id], field)))
    return {'config_json': json.dumps(config, ensure_ascii=False), 'request_id': request_id}
