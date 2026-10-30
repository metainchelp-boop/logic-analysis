# Conversion diagnostic through the existing VPS connection

The public executor uses the existing repository secrets without reading or
copying their values. Eight private fixtures remain in the private repository:
the original six and two report-schema fixtures for c44a663 and abceeb7.
Private qualification run41017595072, attempt1, binds source
ee04b7fb7f863081e5f0712e07b24792b2631578 (tree dc4f52da6da54620d6b4f93ec7753e868a0a3b43).
It runs the original Bundle checks with their two known skipped replays, the
seven baseline/inverse-hunk tests, and twenty pool-first boundary tests: the
c44a live-baseline receipt and rollback, the frozen decoder, store-change
refusal, the retired store contracts against their 49275594 snapshot, and the
actual wire/SSH caps.

Running product c44a66393340314796851f4dd524dad523bd5415 (prepare40346718889,
apply d43ebab98f5941f08146490e48e71aab) is the old side. Target
abceeb737548ada081072df95279d19981b561f7 changes only
naver_runtime/report_output_schema.py (FORMAT_VERSION and output_format).
The live host must match baseline1a107fb029873d44ccfc09b1001c5d85b3dd5e871c008adeadb516e12b72e3cd;
every receipt before c44a keeps5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76.

Reserved for this target only: apply 01330a7419d0494d8bfb74ec1fcb7e28 and
rollback ba912f5af5d34a6985d9415013f90486. The release gate measures prepare,
apply and rollback requests with the actual prepare run ID before any cipher
download or server step. It retains all existing wire, JSON, bootstrap, SSH and
source size limits. No output includes the signed download URL.

Source qualification and deployment do not establish conversion readiness or AI
strategy completion.
