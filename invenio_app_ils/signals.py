# -*- coding: utf-8 -*-
#
# Copyright (C) 2019 CERN.
#
# invenio-app-ils is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Invenio app ils signals."""

from blinker import Namespace

_signals = Namespace()

record_viewed = _signals.signal("record-viewed")
file_downloaded = _signals.signal("file-downloaded")
ils_record_changed = _signals.signal("ils_record_changed")
