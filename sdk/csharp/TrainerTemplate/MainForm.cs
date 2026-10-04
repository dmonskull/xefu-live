using System;
using System.Drawing;
using System.Windows.Forms;
using OgXbox;
using XDevkit;
using XDRPC;

namespace TrainerTemplate
{
    public class MainForm : Form
    {
        private XboxGame game;
        private Freezer freezer;
        private Cheat[] cheats = new Cheat[0];

        private readonly Label status = new Label();
        private readonly CheckedListBox list = new CheckedListBox();
        private readonly TextBox address = new TextBox();
        private readonly ComboBox type = new ComboBox();
        private readonly TextBox value = new TextBox();
        // a WinForms timer, so XDevkit is only ever used from the UI thread
        private readonly Timer freezeTimer = new Timer();

        public MainForm()
        {
            Text = "OG Xbox Trainer";
            ClientSize = new Size(460, 400);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;

            Button connect = new Button { Text = "Connect", Location = new Point(12, 12), Size = new Size(90, 26) };
            connect.Click += Connect;
            status.Location = new Point(112, 17);
            status.Size = new Size(336, 20);
            status.Text = "Not connected";

            Label help = new Label { Text = "Tick a cheat to keep it on:", Location = new Point(12, 50), AutoSize = true };
            list.Location = new Point(12, 70);
            list.Size = new Size(436, 214);
            list.CheckOnClick = true;
            list.ItemCheck += CheatToggled;

            // quick peek and poke with the game's own addresses
            Label at = new Label { Text = "Address", Location = new Point(12, 300), AutoSize = true };
            address.Location = new Point(64, 297);
            address.Size = new Size(90, 22);
            type.Location = new Point(162, 297);
            type.Size = new Size(70, 22);
            type.DropDownStyle = ComboBoxStyle.DropDownList;
            type.Items.AddRange(new object[] { CheatType.Byte, CheatType.Int16, CheatType.Int32, CheatType.Float });
            type.SelectedIndex = 3;
            value.Location = new Point(240, 297);
            value.Size = new Size(80, 22);
            Button read = new Button { Text = "Read", Location = new Point(328, 295), Size = new Size(56, 26) };
            read.Click += ReadValue;
            Button write = new Button { Text = "Write", Location = new Point(392, 295), Size = new Size(56, 26) };
            write.Click += WriteValue;

            Label note = new Label
            {
                Text = "Addresses are the game's own (hex), the ones Ghidra or IDA show for the XBE.\n" +
                       "Cheats live in Cheats.cs.",
                Location = new Point(12, 334),
                Size = new Size(436, 40),
                ForeColor = SystemColors.GrayText,
            };

            Controls.AddRange(new Control[] { connect, status, help, list, at, address, type, value, read, write, note });

            freezeTimer.Interval = 250;
            freezeTimer.Tick += FreezeTick;
            freezeTimer.Start();
        }

        private void Connect(object sender, EventArgs e)
        {
            if (!XboxConnection.ConnectToConsole())
            {
                status.Text = "Could not connect. Is the console the default one in Neighborhood?";
                return;
            }
            IXboxConsole xbCon = XboxConnection.xbCon;
            try
            {
                game = xbCon.OgXbox();
            }
            catch (Exception ex)
            {
                status.Text = ex.Message;
                return;
            }
            freezer = new Freezer(game);

            status.Text = string.Format("{0}  (title {1:X8}, {2})", game.TitleName, game.TitleId, game.Emulator);
            if (!Cheats.Games.TryGetValue(game.TitleId, out cheats)) cheats = new Cheat[0];
            list.Items.Clear();
            foreach (Cheat c in cheats) list.Items.Add(c.Name);
            if (cheats.Length == 0) list.Items.Add("(no cheats for this game yet, add some in Cheats.cs)");

            // XDRPC is only needed for extras like this one. Reading and writing work without it.
            try
            {
                Text = "OG Xbox Trainer - 360 title " + xbCon.GetCurrentTitleId().ToString("X8");
            }
            catch (Exception)
            {
                Text = "OG Xbox Trainer";
            }
        }

        private void CheatToggled(object sender, ItemCheckEventArgs e)
        {
            if (freezer == null || e.Index >= cheats.Length) return;
            Cheat c = cheats[e.Index];
            if (e.NewValue == CheckState.Checked) freezer.Set(c.Address, c.Bytes());
            else freezer.Remove(c.Address);
        }

        private void FreezeTick(object sender, EventArgs e)
        {
            if (freezer == null || freezer.Count == 0) return;
            // skip the round if the player quit the game, OgXbox() finds it again when it is back
            if (!XboxConnection.xbCon.OgXboxRunning()) return;
            freezer.Apply();
        }

        private bool Ready(out uint target)
        {
            target = 0;
            if (game == null || !game.IsAttached)
            {
                status.Text = "Connect first.";
                return false;
            }
            try
            {
                target = Convert.ToUInt32(address.Text.Trim(), 16);
                return true;
            }
            catch (Exception)
            {
                status.Text = "The address has to be hex, like BB85B8.";
                return false;
            }
        }

        private void ReadValue(object sender, EventArgs e)
        {
            uint target;
            if (!Ready(out target)) return;
            try
            {
                switch ((CheatType)type.SelectedItem)
                {
                    case CheatType.Byte: value.Text = game.ReadByte(target).ToString(); break;
                    case CheatType.Int16: value.Text = game.ReadInt16(target).ToString(); break;
                    case CheatType.Float: value.Text = game.ReadFloat(target).ToString(System.Globalization.CultureInfo.InvariantCulture); break;
                    default: value.Text = game.ReadInt32(target).ToString(); break;
                }
                status.Text = string.Format("{0:X8} is at {1:X8} on the 360", target, game.ToHost(target));
            }
            catch (Exception ex)
            {
                status.Text = ex.Message;
            }
        }

        private void WriteValue(object sender, EventArgs e)
        {
            uint target;
            if (!Ready(out target)) return;
            try
            {
                game.WriteBytes(target, Cheat.Encode((CheatType)type.SelectedItem, value.Text.Trim()));
                status.Text = string.Format("Wrote {0} to {1:X8}", value.Text.Trim(), target);
            }
            catch (Exception ex)
            {
                status.Text = ex.Message;
            }
        }
    }
}
