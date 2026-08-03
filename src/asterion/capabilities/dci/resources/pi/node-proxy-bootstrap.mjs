const proxy = process.env.HTTPS_PROXY || process.env.HTTP_PROXY;
const undiciUrl = process.env.ASTERION_PI_UNDICI_URL;

if (proxy && undiciUrl) {
	const { ProxyAgent, setGlobalDispatcher } = await import(undiciUrl);
	setGlobalDispatcher(new ProxyAgent(proxy));
}
