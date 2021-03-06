from datetime import datetime, timedelta

from bitcalm import log
from bitcalm.utils import total_seconds


class ActionPool(object):
    def __init__(self):
        self._actions = []

    def _funcs(self):
        return [a._func for a in self._actions]

    def __iter__(self):
        return iter(sorted(self._actions))

    def add(self, action):
        if action._func in self._funcs():
            return False
        self._actions.append(action)
        action.pool = self
        return True

    def extend(self, actions):
        actions = [a for a in actions if a._func not in self._funcs()]
        self._actions.extend(actions)
        for action in actions:
            action.pool = self
        return len(actions)

    def remove(self, action):
        self._actions.remove(action)
        action.pool = None

    def clear(self):
        if self._actions:
            for a in self._actions:
                a.pool = None
            self._actions = []

    def get(self, func_or_tag):
        """ Returns action identified by it's function or tag
        """
        attr = '_func' if callable(func_or_tag) else 'tag'
        for action in self._actions:
            if getattr(action, attr) == func_or_tag:
                return action
        return None

    def has(self, func_or_tag):
        return bool(self.get(func_or_tag))

    def next(self):
        if self._actions:
            return min(filter(lambda a: a.time is not None, self._actions))
        return None


class Action(object):
    def __init__(self, nexttime, func, *args, **kwargs):
        self.tag = kwargs.pop('tag', None)
        self.pool = None
        self.lastexectime = None
        self._func = func
        if callable(nexttime):
            self._period = 0
            self._next = nexttime
        else:
            self._period = nexttime
            self._next = self._default_next
        start = kwargs.pop('start', None)
        if start is None:
            self.next()
        else:
            self.time = datetime.utcnow() + timedelta(seconds=start)
        self._args = args
        self._kwargs = kwargs
    
    def __str__(self):
        return '%s at %s' % (self._func, self.time)
    
    def __call__(self):
        log.info('Perform action: %s' % self._func)
        self.lastexectime = datetime.utcnow()
        if self._func(*self._args, **self._kwargs):
            self.next()
            log.info('Action %s is complete' % self._func)
        else:
            self.delay()
            log.error('Action %s failed' % self._func)
    
    def __cmp__(self, other):
        return cmp(self.time, other.time)
    
    def _default_next(self):
        return (self.lastexectime or datetime.utcnow()) \
            + timedelta(seconds=self._period)
    
    def next(self):
        self.time = self._next()
    
    def delay(self, period=600):
        self.time = datetime.utcnow() + timedelta(seconds=period)
    
    def time_left(self):
        now = datetime.utcnow()
        if self.time > now:
            return total_seconds(self.time - now)
        return 0


class OneTimeAction(Action):
    def __init__(self, nexttime, func, *args, **kwargs):
        self._followers = kwargs.pop('followers', [])
        # cancel can contain function, tag or action
        self._cancel = kwargs.pop('cancel', [])
        Action.__init__(self, nexttime, func, *args, **kwargs)

    def __call__(self):
        log.info('Perform action: %s' % self._func)
        self.lastexectime = datetime.utcnow()
        if self._func(*self._args, **self._kwargs):
            if self.pool:
                pool = self.pool
                self.pool.remove(self)

                for item in self._cancel:
                    if not isinstance(item, Action):
                        item = pool.get(item)
                        if not item:
                            continue
                    pool.remove(item)

                if self._followers:
                    def grow(a):
                        if isinstance(a, ActionSeed):
                            return a.grow()
                        return a
                    self._followers = map(grow, self._followers)
                    pool.extend(self._followers)
                for follower in self._followers:
                    follower.next()
            log.info('Action %s is complete' % self._func)
        else:
            self.next()


class StepAction(Action):
    def __init__(self, nexttime, func, *args, **kwargs):
        self.step = kwargs.pop('step', 600)
        Action.__init__(self, nexttime, func, *args, **kwargs)

    def __call__(self):
        log.info('Perform action: %s' % self._func)
        result = self._func(*self._args, **self._kwargs)
        self.lastexectime = datetime.utcnow()
        if result == -1:
            self.time = datetime.utcnow() + timedelta(seconds=self.step)
            log.info('Step of action %s is complete' % self._func)
        elif result == 1:
            self.next()
            log.info('Action %s is complete' % self._func)
        else:
            self.delay()
            log.error('Action %s failed' % self._func)


class ActionSeed(object):
    def __init__(self, *args, **kwargs):
        self.cls = kwargs.pop('cls', Action)
        self.args = args
        self.kwargs = kwargs
    
    def grow(self):
        return self.cls(*self.args, **self.kwargs)
