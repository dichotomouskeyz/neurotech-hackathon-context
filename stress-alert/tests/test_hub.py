from dashboard.hub import Hub, drain


def bfi(t):
    return {"type": "bfi", "t": t}


async def test_publish_reaches_every_subscriber_as_one_batch():
    hub = Hub()
    a, b = hub.subscribe(), hub.subscribe()
    hub.publish([bfi(1), bfi(2)])
    assert await drain(a) == [bfi(1), bfi(2)]
    assert await drain(b) == [bfi(1), bfi(2)]


async def test_late_joiner_gets_history_and_latest_status_first():
    hub = Hub(history=2)
    hub.publish([{"type": "status", "source": "feed", "connected": True}, bfi(1)])
    hub.publish([bfi(2), bfi(3)])
    hub.publish([{"type": "status", "source": "feed", "connected": False}])
    batch = await drain(hub.subscribe())
    assert batch == [{"type": "status", "source": "feed", "connected": False}, bfi(2), bfi(3)]


async def test_latest_readouts_survive_signal_history():
    hub = Hub(history=2)
    hr = {"type": "hr", "t": 1, "source": "ecg", "bpm": 70}
    cq = {"type": "cq", "t": 1, "left": 0.9, "right": 0.8}
    hub.publish([hr, cq])
    hub.publish([bfi(2), bfi(3), bfi(4)])
    batch = await drain(hub.subscribe())
    assert hr in batch and cq in batch
    assert batch[-2:] == [bfi(3), bfi(4)]


async def test_slow_subscriber_drops_oldest_not_newest():
    hub = Hub(queue_size=2)
    queue = hub.subscribe()
    hub.publish([bfi(1), bfi(2), bfi(3)])
    assert await drain(queue) == [bfi(2), bfi(3)]


def test_unsubscribe_stops_delivery():
    hub = Hub()
    queue = hub.subscribe()
    hub.unsubscribe(queue)
    hub.publish([bfi(1)])
    assert queue.empty()
    assert hub.subscriber_count == 0
