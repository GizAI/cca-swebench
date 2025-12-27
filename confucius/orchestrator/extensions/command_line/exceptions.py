# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict


class InvalidCommandLineInput(Exception):
    pass


class SessionTerminated(Exception):
    pass


class SessionNotFoundError(Exception):
    pass
