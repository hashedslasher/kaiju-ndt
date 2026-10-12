//---------------------------------------------------------------------------
// INCLUDES
//--------------------------------------------------------------------------
#include "adc/adc.h"
#include "motors/motors.h"
#include "dac/dac.h"
#include "../external/pico_fast_serial/fast_serial.h"

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

    /* First accept one-word commands such as move_x/jog_x/stop_x/read. */
    for (int i = 0; i < (int)(sizeof(command_list) / sizeof(command_t)); ++i) {
        if (strcmp(command, command_list[i].command_name) == 0) {
            char *args = strtok(NULL, "\r\n");
            command_list[i].func(args ? args : "0");
            return;
        }
    }

    /* Preserve the existing two-word commands such as "start acq" and "write dac". */
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

void read_input(char *buffer, int max_len)
{
    int len = fast_serial_read_until(buffer, max_len, '\n'); 
    
    if (len > 0) {
        buffer[len] = '\0';
        if (buffer[len - 1] == '\r') {
            buffer[len - 1] = '\0';
        }
    } else {
        buffer[0] = '\0';
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

    char input[128];
    while (true)
    {
        fast_serial_task();
        motor_service();
        read_input(input, sizeof(input));
        if (input[0] != '\0')
        {
            process_command(input);
        }
    }
}
