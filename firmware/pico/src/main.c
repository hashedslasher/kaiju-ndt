//---------------------------------------------------------------------------
// INCLUDES
//--------------------------------------------------------------------------
#include "adc/adc.h"
#include "motors/motors.h"
#include "dac/dac.h"
#include "../external/pico_fast_serial/fast_serial.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

//---------------------------------------------------------------------------
// GLOBALS
//--------------------------------------------------------------------------

typedef void (*command_func_t)(const char *args);

typedef struct
{
    const char *command_name;
    command_func_t func;
} command_t;

command_t command_list[] = {
    {"start acq", pulse_adc_trigger},
    {"write dac", dac},
    {"read", adc},
    {"move_x", move_x},
    {"move_y", move_y},
    {"move_z", move_z},
    {"jog_x", jog_x},
    {"jog_y", jog_y},
    {"jog_z", jog_z},
    {"stop_x", stop_x},
    {"stop_y", stop_y},
    {"stop_z", stop_z},
};

void process_command(char *input)
{
    char *command = strtok(input, " \r\n");
    if (command == NULL) {
        return;
    }

    for (int i = 0; i < (int)(sizeof(command_list) / sizeof(command_t)); ++i) {
        if (strcmp(command, command_list[i].command_name) == 0) {
            char *args = strtok(NULL, "\r\n");
            command_list[i].func(args ? args : "0");
            return;
        }
    }

    char *subcommand = strtok(NULL, " \r\n");
    if (subcommand != NULL) {
        char full_command[50];
        snprintf(full_command, sizeof(full_command), "%s %s", command, subcommand);

        for (int i = 0; i < (int)(sizeof(command_list) / sizeof(command_t)); ++i) {
            if (strcmp(full_command, command_list[i].command_name) == 0) {
                char *args = strtok(NULL, "\r\n");
                command_list[i].func(args ? args : "0");
                return;
            }
        }

        printf("Unknown command: %s %s\n", command, subcommand);
        return;
    }

    printf("Unknown command: %s\n", command);
}

#define COMMAND_BUFFER_SIZE       128u
#define MAX_SERIAL_BYTES_PER_POLL  64u

static void poll_serial_commands(void)
{
    static char command_buffer[COMMAND_BUFFER_SIZE];
    static size_t command_length = 0;
    static bool discard_oversized_line = false;

    for (uint32_t bytes = 0;
         bytes < MAX_SERIAL_BYTES_PER_POLL && fast_serial_read_available() > 0;
         ++bytes) {
        char ch;
        if (fast_serial_read_atomic(&ch, 1) != 1) {
            break;
        }

        if (ch == '\n') {
            if (!discard_oversized_line && command_length > 0) {
                command_buffer[command_length] = '\0';
                process_command(command_buffer);
            }
            command_length = 0;
            discard_oversized_line = false;
            break;
        }

        if (discard_oversized_line || ch == '\r') {
            continue;
        }

        if (command_length < sizeof(command_buffer) - 1) {
            command_buffer[command_length++] = ch;
        } else {
            command_length = 0;
            discard_oversized_line = true;
        }
    }
}


//---------------------------------------------------------------------------
// MAIN FUNCTION
//---------------------------------------------------------------------------

int main()
{
    fast_serial_init();
    while (!tud_mounted())
    {
        tud_task();
        tight_loop_contents();
    }
    
    sleep_ms(100);
    pio_adc_init();
    sleep_ms(100);
    dac_init();
    sleep_ms(100);
    motor_setup();

    while (true)
    {
        fast_serial_task();
        motor_service();
        poll_serial_commands();
    }
}
