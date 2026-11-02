// The runner points actions at the in-VM proxy: link-local when the image's
// proxy supports container access, loopback otherwise.
const proxies = ['http://169.254.77.1:8448/', 'http://127.0.0.1:8448/'];
const url = process.env.ACTIONS_RESULTS_URL;
console.log(`JavaScript action ACTIONS_RESULTS_URL=${url}`);
if (!proxies.includes(url)) {
  console.log('FAIL: JavaScript actions do not use the Celesto cache proxy');
  process.exit(1);
}
console.log('PASS');
