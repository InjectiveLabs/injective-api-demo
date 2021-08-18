import asyncio
import logging
import grpc
import os
import sys

_current_dir = os.path.dirname(os.path.abspath(__file__))
SDK_PATH = os.path.join(_current_dir, "sdk_python")
sys.path.insert(0, SDK_PATH)

import exchange_api.injective_accounts_rpc_pb2 as accounts_rpc_pb
import exchange_api.injective_accounts_rpc_pb2_grpc as accounts_rpc_grpc
import exchange_api.injective_derivative_exchange_rpc_pb2 as derivative_exchange_rpc_pb
import exchange_api.injective_derivative_exchange_rpc_pb2_grpc as derivative_exchange_rpc_grpc
import exchange_api.injective_exchange_rpc_pb2 as exchange_rpc_pb
import exchange_api.injective_exchange_rpc_pb2_grpc as exchange_rpc_grpc
import exchange_api.injective_insurance_rpc_pb2 as insurance_rpc_pb
import exchange_api.injective_insurance_rpc_pb2_grpc as insurance_rpc_grpc
import exchange_api.injective_oracle_rpc_pb2 as oracle_rpc_pb
import exchange_api.injective_oracle_rpc_pb2_grpc as oracle_rpc_grpc
import exchange_api.injective_spot_exchange_rpc_pb2 as spot_exchange_rpc_pb
import exchange_api.injective_spot_exchange_rpc_pb2_grpc as spot_exchange_rpc_grpc


async def main() -> None:
    async with grpc.aio.insecure_channel('localhost:9910') as channel:
        exchange_rpc = exchange_rpc_grpc.InjectiveExchangeRPCStub(channel)
        spot_exchange_rpc = spot_exchange_rpc_grpc.InjectiveSpotExchangeRPCStub(
            channel)

        resp = await exchange_rpc.Version(exchange_rpc_pb.VersionRequest())
        print("-- Connected to Injective Exchange (version: %s, built %s)" %
              (resp.version, resp.meta_data["BuildDate"]))

        resp = await spot_exchange_rpc.Markets(spot_exchange_rpc_pb.MarketsRequest())
        print("\n-- Available markets:")
        for m in resp.markets:
            print(m.ticker, "=", m.market_id)

        selected_market = resp.markets[0]
        print("\n-- Watching for order updates on market %s" %
              selected_market.ticker)
        stream_req = spot_exchange_rpc_pb.StreamOrdersRequest(
            market_id=selected_market.market_id)
        orders_stream = spot_exchange_rpc.StreamOrders(stream_req)
        async for order in orders_stream:
            print("\n-- Order Update:", order)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.get_event_loop().run_until_complete(main())
