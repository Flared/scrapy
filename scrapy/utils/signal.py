"""Helper functions for working with signals"""

import logging

from twisted.internet.defer import maybeDeferred, DeferredList, Deferred, FirstError
from twisted.python.failure import Failure

from pydispatch.dispatcher import Any, Anonymous, liveReceivers, \
    getAllReceivers, disconnect
from pydispatch.robustapply import robustApply
from scrapy.utils.log import failure_to_exc_info

logger = logging.getLogger(__name__)


class _IgnoredException(Exception):
    pass


def send_catch_log(signal=Any, sender=Anonymous, *arguments, **named):
    """Like pydispatcher.robust.sendRobust but it also logs errors and returns
    Failures instead of exceptions.
    """
    dont_log = named.pop('dont_log', _IgnoredException)
    spider = named.get('spider', None)
    responses = []
    for receiver in liveReceivers(getAllReceivers(sender, signal)):
        try:
            response = robustApply(receiver, signal=signal, sender=sender,
                *arguments, **named)
            if isinstance(response, Deferred):
                logger.error("Cannot return deferreds from signal handler: %(receiver)s",
                             {'receiver': receiver}, extra={'spider': spider})
        except dont_log:
            result = Failure()
        except Exception:
            result = Failure()
            logger.error("Error caught on signal handler: %(receiver)s",
                         {'receiver': receiver},
                         exc_info=True, extra={'spider': spider})
        else:
            result = response
        responses.append((receiver, result))
    return responses


def send_catch_log_deferred(signal=Any, sender=Anonymous, *arguments, **named):
    """Like send_catch_log but supports returning deferreds on signal handlers.
    Returns a deferred that gets fired once all signal handlers deferreds were
    fired.
    """
    def logerror(failure, recv):
        if dont_log is None or not isinstance(failure.value, dont_log):
            logger.error("Error caught on signal handler: %(receiver)s",
                         {'receiver': recv},
                         exc_info=failure_to_exc_info(failure),
                         extra={'spider': spider})
        return failure

    dont_log = named.pop('dont_log', None)
    spider = named.get('spider', None)
    dfds = []
    for receiver in liveReceivers(getAllReceivers(sender, signal)):
        d = maybeDeferred(robustApply, receiver, signal=signal, sender=sender,
                *arguments, **named)
        d.addErrback(logerror, receiver)
        d.addBoth(lambda result: (receiver, result))
        dfds.append(d)
    d = DeferredList(dfds)
    d.addCallback(lambda out: [x[1] for x in out])
    return d

def send_deferred(signal=Any, sender=Anonymous, *arguments, **named):
    """Like pydispatcher.send but supports returning deferreds on signal handlers.
    Returns a deferred that gets fired once all signal handlers deferreds were
    fired.

    If one signal handler fails, the deffered errback is called.
    """

    spider = named.get('spider', None)
    dfds = []
    for receiver in liveReceivers(getAllReceivers(sender, signal)):
        d = maybeDeferred(robustApply, receiver, signal=signal, sender=sender,
                *arguments, **named)
        d.addCallback(lambda result: (receiver, result))
        dfds.append(d)
    d = DeferredList(dfds, consumeErrors=True, fireOnOneErrback=True)
    def unwrap_firsterror(err):
        failure = err.trap(FirstError)
        return err.value.subFailure
    d.addErrback(unwrap_firsterror)
    d.addCallback(lambda out: [x[1] for x in out])
    return d

def disconnect_all(signal=Any, sender=Any):
    """Disconnect all signal handlers. Useful for cleaning up after running
    tests
    """
    for receiver in liveReceivers(getAllReceivers(sender, signal)):
        disconnect(receiver, signal=signal, sender=sender)
