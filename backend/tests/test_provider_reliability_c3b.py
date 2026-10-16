"""Offline C3B tests. No provider connections, no model credentials."""
from __future__ import annotations

import asyncio
import unittest
import sys
from pathlib import Path
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from jace.model_gateway.reliability import (
    ProviderReliability, ProviderReliabilityError, ReliabilityPolicy,
    guarded_call, guarded_stream, transient_error,
)


async def collect(generator):
    return [item async for item in generator]


class C3BTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_attempts_for_pre_output_503(self):
        tries = 0
        monitor = ProviderReliability()
        policy = ReliabilityPolicy(enabled=True, retries=1)

        async def provider():
            nonlocal tries
            tries += 1
            if tries == 1:
                raise ValueError('Cloud provider returned HTTP 503')
            yield {'message': {'content': 'ready'}, 'done': False}
            yield {'done': True, 'prompt_eval_count': 20, 'eval_count': 5}
        result = await collect(guarded_stream(route_id='openai:x', cloud=True,
                                              policy=policy, monitor=monitor, factory=provider))
        self.assertEqual(tries, 2)
        self.assertEqual(result[0]['message']['content'], 'ready')
        st = monitor.snapshot(policy)['routes'][0]
        self.assertEqual((st['attempts'], st['successes'], st['failures']), (2, 1, 1))
        self.assertEqual((st['input_tokens'], st['output_tokens']), (20, 5))

    async def test_stream_after_first_chunk_does_not_retry(self):
        tries = 0
        monitor = ProviderReliability()
        async def provider():
            nonlocal tries
            tries += 1
            yield {'message': {'content': 'visible'}, 'done': False}
            raise RuntimeError('network request failed')
        result = []
        with self.assertRaises(RuntimeError):
            async for chunk in guarded_stream(route_id='anthropic:x', cloud=True,
                    policy=ReliabilityPolicy(enabled=True, retries=2),monitor=monitor,factory=provider):
                result.append(chunk)
        self.assertEqual(tries, 1)
        self.assertEqual(result[0]['message']['content'], 'visible')

    async def test_never_retry_invalid_key(self):
        tries = 0
        async def provider():
            nonlocal tries
            tries += 1
            raise RuntimeError('Anthropic returned HTTP 401')
            yield {}
        with self.assertRaisesRegex(RuntimeError, '401'):
            await collect(guarded_stream(route_id='anthropic:x', cloud=True,
                policy=ReliabilityPolicy(enabled=True, retries=3),
                monitor=ProviderReliability(),factory=provider))
        self.assertEqual(tries, 1)

    async def test_missing_completion_marker_fails_without_retry(self):
        tries = 0
        async def provider():
            nonlocal tries
            tries += 1
            yield {'message':{'content':'not complete'},'done':False}
        with self.assertRaisesRegex(ProviderReliabilityError, 'completion marker'):
            await collect(guarded_stream(route_id='openai:x', cloud=True,
                policy=ReliabilityPolicy(enabled=True,retries=2),
                monitor=ProviderReliability(),factory=provider))
        self.assertEqual(tries,1)

    async def test_circuit_opens_after_threshold(self):
        t = [100.0]
        clock = lambda: t[0]
        monitor = ProviderReliability(clock=clock)
        policy = ReliabilityPolicy(enabled=True, retries=0, failure_threshold=2, cooldown_seconds=20)
        async def provider():
            raise RuntimeError('HTTP 429')
            yield {}
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                await collect(guarded_stream(route_id='openai:x', cloud=True,
                        policy=policy, monitor=monitor, factory=provider))
        self.assertTrue(monitor.circuit_open('openai:x'))
        with self.assertRaisesRegex(ProviderReliabilityError, 'circuit open'):
            await collect(guarded_stream(route_id='openai:x', cloud=True,
                policy=policy, monitor=monitor, factory=provider))
        t[0] += 21
        self.assertFalse(monitor.circuit_open('openai:x'))

    async def test_provider_circuits_separated_by_model(self):
        t = [1.0]
        mon = ProviderReliability(clock=lambda:t[0]); pol = ReliabilityPolicy(enabled=True,retries=0,failure_threshold=1)
        async def broken():
            raise RuntimeError('HTTP 502'); yield {}
        with self.assertRaises(RuntimeError):
            await collect(guarded_stream(route_id='anthropic:bad', cloud=True,
                policy=pol,monitor=mon,factory=broken))
        self.assertTrue(mon.circuit_open('anthropic:bad'))
        self.assertFalse(mon.circuit_open('anthropic:good'))

    async def test_request_rate_limiting_includes_retries(self):
        t=[100.0]; mon=ProviderReliability(clock=lambda:t[0])
        pol=ReliabilityPolicy(enabled=True,retries=1,requests_per_minute=1)
        async def fail():
            raise RuntimeError('HTTP 500'); yield {}
        with self.assertRaisesRegex(ProviderReliabilityError,'per-minute'):
            await collect(guarded_stream(route_id='openai:x',cloud=True,policy=pol,monitor=mon,factory=fail))
        self.assertEqual(mon.snapshot(pol)['routes'][0]['attempts'], 1)

    async def test_pricing_estimate_and_observed_guard(self):
        mon=ProviderReliability()
        pol=ReliabilityPolicy(enabled=True,retries=0,pricing_json='{"openai:x":{"input_per_million":2,"output_per_million":4}}', observed_cost_limit_usd=.01)
        async def provider():
            yield {'message':{'content':'ok'},'done':False}
            yield {'done':True,'prompt_eval_count':5000,'eval_count':1000}
        await collect(guarded_stream(route_id='openai:x',cloud=True,policy=pol,monitor=mon,factory=provider))
        status=mon.snapshot(pol)
        self.assertAlmostEqual(status['observed_cost_usd'],0.014,places=6)
        with self.assertRaisesRegex(ProviderReliabilityError,'spend limit'):
            await collect(guarded_stream(route_id='openai:x',cloud=True,policy=pol,monitor=mon,factory=provider))

    async def test_budget_fails_closed_on_missing_price(self):
        pol=ReliabilityPolicy(enabled=True, observed_cost_limit_usd=1)
        async def prov():
            yield {'done':True}
        with self.assertRaisesRegex(ProviderReliabilityError,'requires nonzero verified prices'):
            await collect(guarded_stream(route_id='openai:x',cloud=True,policy=pol,monitor=ProviderReliability(),factory=prov))

    async def test_zero_placeholder_prices_cannot_enable_spend_guard(self):
        policy=ReliabilityPolicy(enabled=True,observed_cost_limit_usd=0.5,
            pricing_json='{"openai:x":{"input_per_million":0,"output_per_million":0}}')
        async def prov(): yield {'done':True}
        with self.assertRaisesRegex(ProviderReliabilityError,'nonzero verified prices'):
            await collect(guarded_stream(route_id='openai:x',cloud=True,policy=policy,
                    monitor=ProviderReliability(),factory=prov))

    async def test_local_provider_not_guarded(self):
        mon=ProviderReliability()
        p=ReliabilityPolicy(enabled=True,requests_per_minute=1)
        async def prov():
            yield {'done':True}
        await collect(guarded_stream(route_id='ollama:a',cloud=False,policy=p,monitor=mon,factory=prov))
        self.assertEqual(mon.snapshot(p)['routes'], [])

    async def test_disabled_is_passthrough(self):
        async def fail():
            raise RuntimeError('HTTP 503'); yield {}
        with self.assertRaises(RuntimeError):
            await collect(guarded_stream(route_id='openai:x',cloud=True,policy=ReliabilityPolicy(enabled=False,retries=3),monitor=ProviderReliability(),factory=fail))

    async def test_structured_call_bounded_retry(self):
        n=0
        async def call():
            nonlocal n
            n+=1
            if n==1: raise RuntimeError('network request failed')
            return {'answer': 42}
        got=await guarded_call(route_id='anthropic:x',cloud=True,policy=ReliabilityPolicy(enabled=True,retries=1),monitor=ProviderReliability(),factory=call)
        self.assertEqual(got,{'answer':42}); self.assertEqual(n,2)

    async def test_cancelled_stream_releases_slot(self):
        mon=ProviderReliability(); pol=ReliabilityPolicy(enabled=True)
        async def prov():
            yield {'message':{'content':'one'},'done':False}
            await asyncio.sleep(100)
        stream=guarded_stream(route_id='openai:x',cloud=True,policy=pol,monitor=mon,factory=prov)
        await anext(stream)
        await stream.aclose()
        route=mon.snapshot(pol)['routes'][0]
        self.assertEqual(route['active'],0)
        self.assertEqual(route['failures'],0)

    async def test_snapshot_has_no_prompt_or_error_payload(self):
        mon=ProviderReliability(); pol=ReliabilityPolicy(enabled=True)
        async def fail():
            raise RuntimeError('HTTP 401 secret text');yield {}
        with self.assertRaises(RuntimeError):
            await collect(guarded_stream(route_id='openai:x',cloud=True,policy=pol,monitor=mon,factory=fail))
        dumped=str(mon.snapshot(pol))
        self.assertNotIn('secret text',dumped)
        self.assertIn('non_retryable',dumped)

    async def test_unknown_and_status_categories(self):
        self.assertFalse(transient_error(RuntimeError('HTTP 400')))
        self.assertTrue(transient_error(RuntimeError('OpenAI returned HTTP 429')))
        self.assertFalse(transient_error(RuntimeError('Some completely unknown problem')))

    async def test_pricing_rejects_invalid_numbers(self):
        p=ReliabilityPolicy(enabled=True,pricing_json='{"openai:x":{"input_per_million":-1,"output_per_million":4}}')
        async def prov(): yield {'done':True}
        with self.assertRaisesRegex(ProviderReliabilityError,'non-negative'):
            await collect(guarded_stream(route_id='openai:x',cloud=True,policy=p,monitor=ProviderReliability(),factory=prov))


if __name__ == '__main__':
    unittest.main()
