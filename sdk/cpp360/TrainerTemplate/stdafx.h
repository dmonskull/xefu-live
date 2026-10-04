#pragma once

#include <xtl.h>
#include <stdio.h>

// kernel and xam exports the XDK headers leave out: MmIsAddressValid, ExCreateThread,
// XapiThreadStartup, XamGetCurrentTitleId, XNotifyQueueUI
#include <xkelib.h>

#include "../ogxbox.h"
