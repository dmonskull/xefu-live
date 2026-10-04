using System;
using XDevkit;

namespace OgXbox
{
    /// <summary>
    /// Lets a form reach the Xbox game straight from the console object it already has:
    ///
    ///     Form1.xbCon.OgXbox().WriteFloat(0x00BB85B8, 999f);
    ///
    /// Next to the normal xbCon.WriteFloat and friends, which stay what they are:
    /// big endian writes to 360 addresses.
    /// </summary>
    public static class OgXboxExtensions
    {
        private static readonly object gate = new object();
        private static IXboxConsole owner;
        private static XboxGame game;
        private static DateTime checkedAt;

        /// <summary>The original Xbox game running on this console. Throws XboxGameException if there is none.</summary>
        public static XboxGame OgXbox(this IXboxConsole xbCon)
        {
            lock (gate)
            {
                if (game == null || !ReferenceEquals(owner, xbCon))
                {
                    owner = xbCon;
                    game = new XboxGame(new XDevkitHost(xbCon));
                }
                // look again every few seconds in case the player quit or started another game
                if (!game.IsAttached || (DateTime.UtcNow - checkedAt).TotalSeconds > 3)
                {
                    if (!game.StillRunning() && !game.Attach())
                        throw new XboxGameException("No original Xbox game is running on the console.");
                    checkedAt = DateTime.UtcNow;
                }
                return game;
            }
        }

        /// <summary>True if an original Xbox game is running right now.</summary>
        public static bool OgXboxRunning(this IXboxConsole xbCon)
        {
            try
            {
                return xbCon.OgXbox().IsAttached;
            }
            catch (XboxGameException)
            {
                return false;
            }
        }
    }
}
