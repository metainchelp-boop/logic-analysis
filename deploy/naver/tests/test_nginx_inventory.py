"""Synthetic routing/secret-boundary tests. Never invoke nginx or read config."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nginx_inventory import summarize_nginx


def dump(main, sections=()):
    return '# configuration file /etc/nginx/nginx.conf:\n' + main + '\n' + ''.join(
        '# configuration file ' + path + ':\n' + body + '\n' for path, body in sections)


def server(body='', host='dashboard.metainc.co.kr'):
    return 'server { listen 443 ssl; server_name ' + host + '; ' + body + ' }'


class NginxInventoryTest(unittest.TestCase):
    def summarize(self, body, sections=()):
        return summarize_nginx(dump('http { ' + body + ' }', sections))

    def assert_private(self, result, *secrets):
        serialized = json.dumps(result, ensure_ascii=False)
        for secret in secrets:
            self.assertNotIn(secret, serialized)

    def test_exact_server_location_and_two_distinct_bindings(self):
        result = self.summarize(server('location /naver/ { proxy_pass http://127.0.0.1:5051; }') +
                                server('location /naver/ { proxy_pass http://unix:/run/metainc/naver-relay/relay.sock:; }', 'logic.metainc.co.kr'))
        self.assertTrue(result['resolution_complete'])
        first, second = result['servers']
        self.assertEqual(first['server_names'], ['dashboard.metainc.co.kr'])
        self.assertEqual(first['locations'][0]['proxy_pass'][0]['port'], 5051)
        self.assertEqual(second['locations'][0]['proxy_pass'][0]['socket'], '/run/metainc/naver-relay/relay.sock')
        self.assertEqual(first['locations'][0]['line'], 1)

    def test_nested_includes_expanded_at_their_real_server_and_location(self):
        result = self.summarize('include sites-enabled/*;', [
            ('/etc/nginx/sites-enabled/dashboard.metainc.co.kr', server('include snippets/naver-relay.conf;')),
            ('/etc/nginx/sites-enabled/logic.metainc.co.kr', server('location / { proxy_pass http://127.0.0.1:8000; }', 'logic.metainc.co.kr')),
            ('/etc/nginx/snippets/naver-relay.conf', 'location ^~ /naver/ {\n include proxy_params;\n}'),
            ('/etc/nginx/proxy_params', 'proxy_pass\n http://127.0.0.1:5051;\nproxy_set_header X-Real-IP $remote_addr;')])
        self.assertEqual(result['status'], 'ok')
        first = result['servers'][0]
        self.assertEqual(first['locations'][0]['source'], 'file-4')
        self.assertEqual(first['locations'][0]['proxy_pass'][0]['port'], 5051)
        self.assertTrue(first['locations'][0]['policies']['real_ip_overwrite'])
        self.assertEqual(result['servers'][1]['locations'][0]['proxy_pass'][0]['port'], 8000)
        self.assertEqual(len(result['includes']), 3)

    def test_glob_does_not_cross_directory_separator(self):
        result = self.summarize('include conf.d/*.conf;', [
            ('/etc/nginx/conf.d/a.conf', server()),
            ('/etc/nginx/conf.d/private/b.conf', server(host='logic.metainc.co.kr'))])
        self.assertEqual(len(result['servers']), 1)
        self.assertIn('unreferenced_file_sections', result['errors'])

    def test_quotes_comments_escaped_delimiters_and_multiline_values(self):
        result = self.summarize(server('''
            # } ; ignored secret comment
            location "= /not-a-location" { proxy_set_header X-Secret "not;{#parsed}"; }
            location = /naver { proxy_pass
                 "http://127.0.0.1:5051";
                 proxy_set_header X-Custom "CANARY_QUOTED
# configuration file /etc/nginx/private-canary:
;{}"; }
            proxy_set_header X-Escaped CANARY_ESCAPED\\#\\;\\{;
        '''))
        self.assertEqual(len(result['files']), 1)
        self.assertEqual(result['servers'][0]['locations'][0]['path'], '/naver')
        self.assertEqual(result['servers'][0]['locations'][0]['modifier'], '=')
        self.assertEqual(result['servers'][0]['locations'][0]['proxy_pass'][0]['port'], 5051)
        self.assert_private(result, 'CANARY_QUOTED', 'private-canary', 'CANARY_ESCAPED', 'not;{#parsed}')

    def test_no_unknown_server_file_location_header_or_auth_value_is_emitted(self):
        secrets = ('CANARY_SERVER', 'CANARY_FILE', 'CANARY_LOCATION', 'CANARY_HEADER', 'CANARY_AUTH')
        result = self.summarize('include sites-enabled/*;', [
            ('/etc/nginx/sites-enabled/CANARY_FILE', server('location /CANARY_LOCATION { proxy_set_header Authorization CANARY_HEADER; auth_basic_user_file /CANARY_AUTH; }')),
            ('/etc/nginx/sites-enabled/private', server('location / { proxy_pass http://127.0.0.1:9999; }', 'CANARY_SERVER'))])
        self.assertEqual(result['redacted_server_count'], 1)
        self.assertIn('redacted_server_context_unverified', result['errors'])
        self.assertEqual(result['servers'][0]['locations'], [])
        self.assertTrue(result['files'][1]['redacted'])
        self.assert_private(result, *secrets)

    def test_certificates_are_path_only_and_domain_and_filename_allowlisted(self):
        result = self.summarize(server('''
            ssl_certificate /etc/letsencrypt/live/dashboard.metainc.co.kr-0001/fullchain.pem;
            ssl_certificate_key /etc/letsencrypt/live/logic.metainc.co.kr/privkey.pem;
            ssl_certificate /etc/letsencrypt/live/CANARY_CERT/fullchain.pem;
            ssl_certificate_key /CANARY_KEY;
        '''))
        certs = result['servers'][0]['certificates']
        self.assertEqual(certs[0]['path'], '/etc/letsencrypt/live/dashboard.metainc.co.kr-0001/fullchain.pem')
        self.assertEqual(certs[1]['path'], '/etc/letsencrypt/live/logic.metainc.co.kr/privkey.pem')
        self.assertIsNone(certs[2]['path'])
        self.assert_private(result, 'CANARY_CERT', 'CANARY_KEY')

    def test_named_upstream_requires_known_name_and_resolved_safe_endpoints(self):
        result = self.summarize('upstream naver_relay { server 127.0.0.1:5051; server [::1]:5052; }' +
                                server('location /naver { proxy_pass http://naver_relay; }'))
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([p['port'] for p in result['servers'][0]['locations'][0]['proxy_pass'][0]['endpoints']], [5051, 5052])
        for upstream in ('CANARY_UPSTREAM', 'naver_relay'):
            with self.subTest(upstream=upstream):
                bad = self.summarize('upstream ' + upstream + ' { server CANARY_ADDRESS:5051; }' + server('location /naver { proxy_pass http://' + upstream + '; }'))
                self.assertFalse(bad['resolution_complete'])
                self.assert_private(bad, 'CANARY_UPSTREAM', 'CANARY_ADDRESS')

    def test_unknown_and_variable_proxy_targets_are_redacted(self):
        for value in ('http://CANARY_HOST:5051/CANARY_PATH', 'http://$CANARY_VARIABLE', 'http://${CANARY_VARIABLE}', 'https://user:CANARY_PASSWORD@localhost:5051', 'http://unix:/CANARY_SOCKET:;'):
            with self.subTest(value=value):
                result = self.summarize(server('location /naver { proxy_pass ' + value + '; }'))
                self.assertFalse(result['resolution_complete'])
                self.assert_private(result, 'CANARY_HOST', 'CANARY_PATH', 'CANARY_VARIABLE', 'CANARY_PASSWORD', 'CANARY_SOCKET')

    def test_known_endpoint_does_not_expose_uri_or_claim_effective_route(self):
        result = self.summarize(server('location /naver { proxy_pass http://127.0.0.1:5051/CANARY_CUSTOMER; }'))
        target = result['servers'][0]['locations'][0]['proxy_pass'][0]
        self.assertEqual(target['port'], 5051)
        self.assertTrue(target['uri_present'])
        self.assertFalse(result['resolution_complete'])
        self.assert_private(result, 'CANARY_CUSTOMER')

    def test_regex_and_unknown_overlapping_locations_are_explicitly_incomplete(self):
        result = self.summarize(server('location /naver { proxy_pass http://127.0.0.1:5051; } location ~ "^/naver/CANARY_REGEX" { return 403; } location /naver/CANARY_CUSTOMER { return 403; }'))
        self.assertIn('regex_location_present', result['servers'][0]['unresolved'])
        self.assertIn('other_location_present', result['servers'][0]['unresolved'])
        self.assertEqual(len(result['servers'][0]['locations']), 1)
        self.assert_private(result, 'CANARY_REGEX', 'CANARY_CUSTOMER')

    def test_target_under_unknown_parent_preserves_uncertainty(self):
        result = self.summarize(server('location /CANARY_PARENT { location /naver { proxy_pass http://127.0.0.1:5051; } }'))
        location = result['servers'][0]['locations'][0]
        self.assertEqual(location['parent_location'], 'location-1')
        self.assertFalse(location['context_known'])
        self.assert_private(result, 'CANARY_PARENT')

    def test_http_inherited_routing_is_not_silently_treated_as_absent(self):
        result = self.summarize('root /CANARY_HTTP_ROOT;' + server('location /naver {}'))
        self.assertIn('http_inherited_routing_unverified', result['errors'])
        self.assertFalse(result['resolution_complete'])
        self.assert_private(result, 'CANARY_HTTP_ROOT')

    def test_policy_output_is_boolean_and_does_not_expose_arbitrary_values(self):
        result = self.summarize(server('''location /naver/ {
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header Authorization "Bearer CANARY_TOKEN";
            access_log off; error_log /dev/null crit;
            add_header Cache-Control no-store always;
            add_header Referrer-Policy no-referrer always;
            proxy_buffering off; proxy_request_buffering off;
            proxy_read_timeout 60s; client_max_body_size 2m;
        }'''))
        policies = result['servers'][0]['locations'][0]['policies']
        self.assertTrue(all(policies.values()))
        self.assertTrue(all(type(v) is bool for v in policies.values()))
        self.assert_private(result, 'CANARY_TOKEN', 'Bearer', 'Authorization')
        self.assertEqual(result['policy_semantics'], 'local_directive_presence_not_effective_inheritance')
        self.assertEqual(result['routing_semantics'], 'configuration_structure_only_not_request_matching')

    def test_unrecognized_backslash_escape_does_not_turn_private_name_into_known_host(self):
        result = self.summarize(server(host='dashboard.metainc.co.\\kr'))
        self.assertEqual(result['servers'], [])
        self.assertEqual(result['redacted_server_count'], 1)
        self.assertFalse(result['resolution_complete'])

    def test_static_paths_only_from_exact_allowlist(self):
        result = self.summarize(server('root /root/logic-analysis-deploy/frontend/dist; location / { alias /CANARY_STATIC; }'))
        self.assertEqual(result['servers'][0]['static_paths'][0]['path'], '/root/logic-analysis-deploy/frontend/dist')
        self.assertTrue(result['servers'][0]['locations'][0]['static_paths'][0]['redacted'])
        self.assert_private(result, 'CANARY_STATIC')

    def test_include_cycle_missing_and_variable_targets_remain_unresolved(self):
        for body, sections, expected in (
            ('include snippets/naver-relay.conf;', [('/etc/nginx/snippets/naver-relay.conf', 'include nginx.conf;')], 'include_cycle'),
            ('include CANARY_MISSING;', [], 'include_unresolved'),
            ('include $CANARY_VARIABLE;', [], 'include_unresolved'),
        ):
            with self.subTest(expected=expected):
                result = self.summarize(body, sections)
                self.assertIn(expected, result['errors'])
                self.assertFalse(result['resolution_complete'])
                self.assert_private(result, 'CANARY_MISSING', 'CANARY_VARIABLE')

    def test_duplicate_dump_and_server_and_upstream_are_not_silently_collapsed(self):
        result = summarize_nginx(dump('http {}', [('/etc/nginx/nginx.conf', 'CANARY_DUPLICATE;')]))
        self.assertIn('duplicate_file_section', result['errors'])
        self.assert_private(result, 'CANARY_DUPLICATE')
        result = self.summarize(server() + server())
        self.assertIn('duplicate_server_mapping', result['errors'])
        result = self.summarize('upstream naver_relay { server 127.0.0.1:5051; } upstream naver_relay { server 127.0.0.1:5052; }' + server('location /naver { proxy_pass http://naver_relay; }'))
        self.assertIn('duplicate_upstream', result['errors'])
        self.assertIn('proxy_unresolved', result['servers'][0]['unresolved'])

    def test_parse_failure_and_truncation_never_look_like_successful_empty_config(self):
        for source in ('CANARY_RAW', dump('http {'), dump('http { "CANARY_UNCLOSED'), dump('http { server_name CANARY_TRAILING'), dump('http { ; }'), dump('http { location x { }}}'), dump('http { x "CANARY"suffix; }'), dump('http { x CANARY\\')):
            with self.subTest(source=source):
                result = summarize_nginx(source)
                self.assertEqual(result['status'], 'error')
                self.assertFalse(result['resolution_complete'])
                self.assertTrue(result['errors'])
                self.assert_private(result, 'CANARY')

    def test_input_and_nesting_and_include_depth_limits_fail_closed(self):
        for source in (None, 'CANARY' * 400000, dump('http { x "CANARY\x00"; }'), dump('a { ' * 70 + '}' * 70)):
            result = summarize_nginx(source)
            self.assertEqual(result['status'], 'error')
            self.assert_private(result, 'CANARY')
        sections = [('/etc/nginx/part' + str(n), 'include part' + str(n + 1) + ';') for n in range(34)]
        result = summarize_nginx(dump('include part0;', sections))
        self.assertIn('include_depth_limit', result['errors'])

    def test_unknown_listen_address_and_options_are_redacted_or_unresolved(self):
        result = self.summarize('server { listen CANARY_IP:443; server_name ad.metainc.co.kr; }')
        self.assertIsNone(result['servers'][0]['listen'][0]['address'])
        self.assert_private(result, 'CANARY_IP')
        result = self.summarize('server { listen [::]:443 ssl default_server CANARY_OPTION; server_name ad.metainc.co.kr; }')
        listener = result['servers'][0]['listen'][0]
        self.assertEqual(listener['address'], '[::]')
        self.assertTrue(listener['default_server'])
        self.assertIn('listen_unresolved', result['servers'][0]['unresolved'])
        self.assert_private(result, 'CANARY_OPTION')


if __name__ == '__main__':
    unittest.main()
